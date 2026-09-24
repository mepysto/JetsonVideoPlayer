"""MPRIS2 D-Bus 연동: 키보드 미디어 키, GNOME 상단 미디어 위젯, playerctl, KDE Connect(폰)로 플레이어를 조작합니다.

버스 이름: org.mpris.MediaPlayer2.jetson_player
D-Bus 호출은 GLib 메인 루프(GTK 스레드)에서 실행되므로 플레이어 메서드를 직접 호출해도 안전합니다.
"""
import os
from urllib.request import pathname2url

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

BUS_NAME = "org.mpris.MediaPlayer2.jetson_player"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
NS = 1_000_000_000
US = 1_000

LOOP_STATUS = {"all": "Playlist", "one": "Track", "none": "None", "shuffle": "Playlist"}


class MprisService(dbus.service.Object):
    def __init__(self, player):
        DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        self._bus_name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)
        super().__init__(bus, OBJECT_PATH)
        self.player = player
        self._last = {}
        self._last_position_us = 0

    # ---- 속성 계산 ----------------------------------------------------------
    def _metadata(self):
        p = self.player
        if not p.playlist or not (0 <= p.current_index < len(p.playlist)):
            return dbus.Dictionary({"mpris:trackid": dbus.ObjectPath("/org/mpris/MediaPlayer2/TrackList/NoTrack")}, signature="sv")
        path = p.playlist[p.current_index]
        meta = {
            "mpris:trackid": dbus.ObjectPath(f"/org/jetson_player/track/{p.current_index}"),
            "xesam:title": os.path.splitext(os.path.basename(path))[0],
            "xesam:url": path if path.startswith(("http://", "https://")) else f"file://{pathname2url(os.path.abspath(path))}",
            "xesam:album": os.path.basename(os.path.dirname(path)),
        }
        if p.duration_ns > 0:
            meta["mpris:length"] = dbus.Int64(p.duration_ns // US)
        index = getattr(p, "thumb_index", None)
        if index and index.get("files"):
            art = os.path.join(index["dir"], index["files"][min(len(index["files"]) - 1, len(index["files"]) // 5)])
            meta["mpris:artUrl"] = f"file://{pathname2url(art)}"
        return dbus.Dictionary(meta, signature="sv")

    def _player_props(self):
        p = self.player
        has_video = bool(p.playlist) and p.pipeline is not None
        status = "Stopped" if not has_video else ("Playing" if p.is_playing else "Paused")
        return {
            "PlaybackStatus": status,
            "LoopStatus": LOOP_STATUS.get(p.repeat_mode, "None"),
            "Rate": dbus.Double(p.playback_rate),
            "Shuffle": dbus.Boolean(p.repeat_mode == "shuffle"),
            "Metadata": self._metadata(),
            "Volume": dbus.Double(min(2.0, p.volume_scale.get_value() / 100.0) if not p.is_muted else 0.0),
            "Position": dbus.Int64(max(0, p.last_known_pos_ns) // US),
            "MinimumRate": dbus.Double(0.25),
            "MaximumRate": dbus.Double(3.0),
            "CanGoNext": dbus.Boolean(len(p.playlist) > 1),
            "CanGoPrevious": dbus.Boolean(len(p.playlist) > 1),
            "CanPlay": dbus.Boolean(has_video),
            "CanPause": dbus.Boolean(has_video),
            "CanSeek": dbus.Boolean(has_video and p.duration_ns > 0),
            "CanControl": dbus.Boolean(True),
        }

    def _root_props(self):
        return {
            "CanQuit": True, "CanRaise": True, "CanSetFullscreen": True,
            "Fullscreen": dbus.Boolean(self.player.is_fullscreen),
            "HasTrackList": False,
            "Identity": "Jetson Video Player",
            "DesktopEntry": "jetson-player",
            "SupportedUriSchemes": dbus.Array(["file", "https"], signature="s"),
            "SupportedMimeTypes": dbus.Array(["video/mp4", "video/x-matroska", "video/webm", "video/quicktime", "video/x-msvideo"], signature="s"),
        }

    def update(self):
        """[메인 스레드, 주기 호출] 바뀐 속성만 PropertiesChanged로 알리고, 위치가 튀면 Seeked를 보냅니다."""
        props = self._player_props()
        position = int(props.pop("Position"))
        changed = {k: v for k, v in props.items() if self._last.get(k) != v}
        if changed:
            self._last.update(changed)
            self.PropertiesChanged(PLAYER_IFACE, changed, [])
        # 재생 흐름과 맞지 않는 위치 변화(탐색) 감지: 0.5초 주기 기준 2초 이상 차이
        expected = self._last_position_us + (500_000 * self.player.playback_rate if self.player.is_playing else 0)
        if abs(position - expected) > 2_000_000:
            self.Seeked(dbus.Int64(position))
        self._last_position_us = position

    # ---- org.mpris.MediaPlayer2 --------------------------------------------
    @dbus.service.method(ROOT_IFACE)
    def Raise(self):
        self.player.present()

    @dbus.service.method(ROOT_IFACE)
    def Quit(self):
        self.player.quit_player()

    # ---- org.mpris.MediaPlayer2.Player --------------------------------------
    @dbus.service.method(PLAYER_IFACE)
    def Next(self):
        self.player.play_next_video()

    @dbus.service.method(PLAYER_IFACE)
    def Previous(self):
        self.player.play_prev_video()

    @dbus.service.method(PLAYER_IFACE)
    def Pause(self):
        if self.player.is_playing:
            self.player.toggle_play_pause()

    @dbus.service.method(PLAYER_IFACE)
    def Play(self):
        if not self.player.is_playing:
            self.player.toggle_play_pause()

    @dbus.service.method(PLAYER_IFACE)
    def PlayPause(self):
        self.player.toggle_play_pause()

    @dbus.service.method(PLAYER_IFACE)
    def Stop(self):
        self.Pause()
        self.player.seek_direct(0)

    @dbus.service.method(PLAYER_IFACE, in_signature="x")
    def Seek(self, offset_us):
        self.player.seek_relative(int(offset_us) / 1_000_000)

    @dbus.service.method(PLAYER_IFACE, in_signature="ox")
    def SetPosition(self, track_id, position_us):
        if str(track_id).endswith(f"/{self.player.current_index}"):
            self.player.seek_direct(int(position_us) * US)

    @dbus.service.method(PLAYER_IFACE, in_signature="s")
    def OpenUri(self, uri):
        if uri.startswith("file://"):
            from urllib.parse import unquote
            self.player.load_target_path(unquote(uri[7:]))
        elif uri.startswith("https://"):
            self.player.start_youtube(uri)

    @dbus.service.signal(PLAYER_IFACE, signature="x")
    def Seeked(self, position_us):
        pass

    # ---- org.freedesktop.DBus.Properties -------------------------------------
    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return self.GetAll(interface)[prop]

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface == PLAYER_IFACE:
            return dbus.Dictionary(self._player_props(), signature="sv")
        if interface == ROOT_IFACE:
            return dbus.Dictionary(self._root_props(), signature="sv")
        return dbus.Dictionary({}, signature="sv")

    @dbus.service.method(PROPS_IFACE, in_signature="ssv")
    def Set(self, interface, prop, value):
        p = self.player
        if interface == PLAYER_IFACE:
            if prop == "Volume":
                p.set_volume(max(0.0, min(2.0, float(value))) * 100)
            elif prop == "Rate":
                p.set_playback_rate(float(value))
            elif prop == "LoopStatus":
                p.set_repeat_mode({"Track": "one", "Playlist": "all", "None": "none"}.get(str(value), "all"))
            elif prop == "Shuffle":
                p.set_repeat_mode("shuffle" if bool(value) else "all")
        elif interface == ROOT_IFACE and prop == "Fullscreen":
            if bool(value) != p.is_fullscreen:
                p.toggle_fullscreen()

    @dbus.service.signal(PROPS_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


def start_mpris(player):
    """세션 버스가 없거나 이름이 사용 중이면 조용히 건너뜁니다 (플레이어 기능에는 영향 없음)."""
    try:
        service = MprisService(player)
        print(f"🎛️ [MPRIS] 미디어 키/시스템 미디어 컨트롤 연동: {BUS_NAME}")
        return service
    except Exception as e:
        print(f"ℹ️ MPRIS 연동을 건너뜁니다: {e}")
        return None
