"""GStreamer playbin 파이프라인 구성과 재생 제어"""
import os
import random
from urllib.request import pathname2url

from gi.repository import GLib, GdkX11, Gst, GstVideo

from ..storage import history_cache, resume_cache
from ..subtitles.merge import generate_merged_subtitle_file
from ..subtitles.parse import find_all_matching_subtitles, get_subtitle_color, get_subtitle_label, parse_subtitle_file_events


class PlaybackMixin:
    def seek_to_percent(self, pct):
        if not self.pipeline:
            return
        success, duration = self.pipeline.query_duration(Gst.Format.TIME)
        if success and duration > 0:
            target = int(duration * (pct / 100.0))
            self.last_known_pos_ns = target
            self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, target)

    def play_index_direct(self, idx):
        if self.playlist and 0 <= idx < len(self.playlist):
            self.current_index = idx
            self.play_current_video()

    def set_volume(self, val):
        val = max(0, min(200, val))
        if getattr(self, "volume_scale", None):
            self.volume_scale.set_value(val)
        if getattr(self, "fs_volume_scale", None):
            self.fs_volume_scale.set_value(val)
        if self.pipeline:
            self.pipeline.set_property("volume", val / 100.0)
        boost_str = " (부스트)" if val > 100 else ""
        self.show_osd(f"🔊 볼륨: {int(val)}%{boost_str}")

    def seek_direct(self, target_ns):
        """지정된 나노초 위치로 즉각 Seek합니다."""
        if self.pipeline and target_ns >= 0:
            self.last_known_pos_ns = target_ns
            self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, target_ns)

    def set_playback_rate(self, new_rate):
        """GStreamer 파이프라인에 재생 속도(Playback Rate)를 적용합니다."""
        new_rate = round(max(0.25, min(3.0, new_rate)), 2)
        self.playback_rate = new_rate
        self.rate_applied_on_preroll = True

        if self.pipeline:
            pos = self.last_known_pos_ns
            success, q_pos = self.pipeline.query_position(Gst.Format.TIME)
            if success and q_pos > 0:
                pos = q_pos
                self.last_known_pos_ns = q_pos

            flags = Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT
            res = self.pipeline.seek(
                self.playback_rate,
                Gst.Format.TIME,
                flags,
                Gst.SeekType.SET,
                pos,
                Gst.SeekType.NONE,
                -1
            )
            if not res:
                print(f"⚠️ 재생 속도 {new_rate:.2f}x 설정 실패")
            else:
                print(f"⚡ [재생 속도 변경] {new_rate:.2f}x (현재 위치: {self.format_time(pos)})")

        self.update_speed_button_ui()
        self.show_osd(f"⚡ 속도: {self.playback_rate:.2f}x")

    def step_volume(self, delta):
        """볼륨을 delta(%)만큼 조절합니다 (0~200%)."""
        self.volume_scale.set_value(max(0, min(200, self.volume_scale.get_value() + delta)))

    def frame_step(self, direction):
        """일시정지 상태에서 한 프레임 이동합니다. 뒤로 가기는 GStreamer 제약상 약 1프레임(40ms) 이전 위치로 정밀 탐색합니다."""
        if not self.pipeline:
            return
        if self.is_playing:
            self.toggle_play_pause()
        if direction > 0:
            self.pipeline.send_event(Gst.Event.new_step(Gst.Format.BUFFERS, 1, abs(self.playback_rate), True, False))
            self.show_osd("⏵ 다음 프레임", timeout_ms=600)
        else:
            ok, pos = self.pipeline.query_position(Gst.Format.TIME)
            if ok:
                target = max(0, pos - 40 * Gst.MSECOND)
                self.last_known_pos_ns = target
                self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, target)
                self.show_osd("⏴ 이전 프레임", timeout_ms=600)

    def step_playback_rate(self, delta):
        """현재 재생 속도에서 delta만큼 속도를 증감합니다."""
        new_rate = self.playback_rate + delta
        self.set_playback_rate(new_rate)

    def reset_playback_rate(self):
        """재생 속도를 1.0x (기본값)으로 복원합니다."""
        self.set_playback_rate(1.0)

    def toggle_mute(self):
        """음소거 상태를 토글합니다."""
        self.is_muted = not self.is_muted
        if self.is_muted:
            if hasattr(self, "volume_scale"):
                self.pre_mute_volume = self.volume_scale.get_value()
                self.volume_scale.set_value(0)
            if getattr(self, "fs_volume_scale", None):
                self.fs_volume_scale.set_value(0)
            if self.pipeline:
                self.pipeline.set_property("volume", 0.0)
            self.show_osd("🔇 음소거")
            lbl = "🔇"
        else:
            restore_val = self.pre_mute_volume if self.pre_mute_volume > 0 else 50
            if hasattr(self, "volume_scale"):
                self.volume_scale.set_value(restore_val)
            if getattr(self, "fs_volume_scale", None):
                self.fs_volume_scale.set_value(restore_val)
            if self.pipeline:
                self.pipeline.set_property("volume", restore_val / 100.0)
            self.show_osd(f"🔊 볼륨: {int(restore_val)}%")
            lbl = "◖)))"
        if getattr(self, "mute_btn", None):
            self.mute_btn.set_label(lbl)
        if getattr(self, "fs_mute_btn", None):
            self.fs_mute_btn.set_label(lbl)

    def cycle_repeat_mode(self):
        """재생 모드를 순환 전환합니다 (전체 반복 -> 1곡 반복 -> 순차 후 정지 -> 셔플)."""
        modes = ["all", "one", "none", "shuffle"]
        cur_idx = modes.index(self.repeat_mode) if self.repeat_mode in modes else 0
        new_mode = modes[(cur_idx + 1) % len(modes)]
        self.set_repeat_mode(new_mode)

    def set_repeat_mode(self, mode):
        self.repeat_mode = mode
        icons = {
            "all": ("🔁 전체 반복", "🔁"),
            "one": ("🔂 1곡 반복", "🔂"),
            "none": ("➡️ 순차 재생 후 정지", "➡️"),
            "shuffle": ("🔀 셔플 무작위 재생", "🔀")
        }
        name, icon = icons.get(mode, ("🔁 전체 반복", "🔁"))
        self.show_osd(name)
        if getattr(self, "repeat_btn", None):
            self.repeat_btn.set_label(icon)
            self.repeat_btn.set_tooltip_text(f"재생 모드: {name}")

    def cycle_audio_track(self):
        """오디오 트랙을 순환 변경합니다."""
        if not self.pipeline:
            return
        try:
            n_audio = self.pipeline.get_property("n-audio")
            self.n_audio_tracks = n_audio
            if n_audio <= 1:
                self.show_osd("🎵 오디오 트랙: 단일 트랙")
                return
            cur = self.pipeline.get_property("current-audio")
            next_track = (cur + 1) % n_audio
            self.set_audio_track(next_track)
        except Exception:
            pass

    def set_audio_track(self, track_idx):
        if not self.pipeline:
            return
        try:
            self.pipeline.set_property("current-audio", track_idx)
            self.current_audio_track = track_idx
            self.show_osd(f"🎵 오디오 트랙 {track_idx + 1}/{max(1, self.n_audio_tracks)}")
            print(f"🎵 [오디오 트랙 변경] 트랙 {track_idx + 1}/{max(1, self.n_audio_tracks)}")
        except Exception as e:
            print(f"⚠️ 오디오 트랙 변경 실패: {e}")

    def on_source_setup(self, playbin, source):
        """네트워크 스트리밍(HTTP/HTTPS) 소스에 User-Agent 및 SSL 설정을 주입합니다."""
        if source.find_property("user-agent"):
            source.set_property("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        if source.find_property("ssl-strict"):
            source.set_property("ssl-strict", False)

    def on_deep_element_added(self, bin_elem, sub_bin, element):
        """
        GStreamer 하위 요소 생성 시 젯슨 HW 디코더(nvv4l2decoder) 및 비디오 싱크(nveglglessink)를 감지하여 
        DPB 프레임 버퍼(num-extra-surfaces=32), disable-dpb low-latency 모드, 동적 메모리 할당, 
        고성능 모드, 프레임 드랍 0 및 화면 왜곡 방지 옵션을 동적 설정합니다.
        """
        factory = element.get_factory()
        fname = factory.get_name() if factory else ""
        ename = element.get_name()
        klass = factory.get_metadata("klass") if factory else ""
        if klass and "Decoder" in klass and "Video" in klass and fname not in self.decoder_names:
            self.decoder_names.add(fname)
            acceleration = "NVDEC 하드웨어" if fname == "nvv4l2decoder" else "소프트웨어 fallback"
            print(f"🎬 [선택된 비디오 디코더] {fname} ({acceleration})")

        if "dav1d" in fname or "dav1d" in ename:
            if element.find_property("max-threads"):
                element.set_property("max-threads", 6)
        if "nvv4l2decoder" in fname or "nvv4l2decoder" in ename:
            # NVDEC 하드웨어 디코더 파라미터 최적화
            if element.find_property("enable-max-performance"):
                element.set_property("enable-max-performance", True)
            if element.find_property("num-extra-surfaces"):
                element.set_property("num-extra-surfaces", 32)
            if element.find_property("qos"):
                element.set_property("qos", False)
            if element.find_property("drop-on-latency"):
                element.set_property("drop-on-latency", False)
            if element.find_property("drop-frame-interval"):
                element.set_property("drop-frame-interval", 0)
            if element.find_property("max-errors"):
                element.set_property("max-errors", -1)

        if "nvvidconv" in fname or "nvvidconv" in ename:
            if element.find_property("output-buffers"):
                element.set_property("output-buffers", 32)
            if element.find_property("interpolation-method"):
                # 최고 품질 보간 알고리즘 (5: Nicest 10-tap) 적용하여 픽셀 선명도 극대화
                element.set_property("interpolation-method", 5)
        if "nveglglessink" in fname or "nveglglessink" in ename:
            if element.find_property("force-aspect-ratio"):
                element.set_property("force-aspect-ratio", True)

        # 자막 렌더링 요소 최적화 (외곽선, Noto Sans CJK 한글/한자 유니버설 폰트, 하단 중앙 정렬, 자동 줄바꿈, 완벽한 A/V 싱크)
        if any(k in fname or k in ename for k in ["textoverlay", "subtitleoverlay", "textrender", "playsink"]):
            if "textoverlay" in fname or "textoverlay" in ename or "subtitleoverlay" in fname or "subtitleoverlay" in ename:
                self.subtitle_overlay_element = element
                if element not in self.subtitle_overlays:
                    self.subtitle_overlays.append(element)
            if element.find_property("font-desc"):
                element.set_property("font-desc", self.get_current_subtitle_font_desc())
            if element.find_property("subtitle-font-desc"):
                element.set_property("subtitle-font-desc", self.get_current_subtitle_font_desc())
            if element.find_property("valignment"):
                element.set_property("valignment", 1)  # bottom
            if element.find_property("halignment"):
                element.set_property("halignment", 1)  # center
            if element.find_property("line-alignment"):
                element.set_property("line-alignment", 1)  # center
            if element.find_property("wrap-mode"):
                element.set_property("wrap-mode", 2)  # wordchar (화면 폭 초과 시 자동 줄바꿈)
            if element.find_property("draw-outline"):
                element.set_property("draw-outline", True)
            if element.find_property("draw-shadow"):
                element.set_property("draw-shadow", False)
            if element.find_property("outline-color"):
                element.set_property("outline-color", 0xFF000000)
            if element.find_property("color"):
                element.set_property("color", 0xFFFFFFFF)
            if element.find_property("wait-text"):
                # GStreamer A/V 및 자막 타임스탬프 100% 정밀 동기화
                element.set_property("wait-text", True)
            if element.find_property("shaded-background"):
                element.set_property("shaded-background", False)
            if element.find_property("auto-resize"):
                element.set_property("auto-resize", False)
        if "subparse" in fname or "subparse" in ename:
            if element.find_property("subtitle-encoding"):
                element.set_property("subtitle-encoding", "UTF-8")

    def play_current_video(self, start_position_ns=0):
        """[성능 최적화] 영상 전환 및 다중 자막 변경 시 파이프라인 자원을 완전 세척 후 신규 구축합니다."""
        if not self.playlist or self.current_index < 0 or self.current_index >= len(self.playlist):
            return

        video_path = self.playlist[self.current_index]
        self.rate_applied_on_preroll = False

        # 삭제/이동된 파일은 건너뛰고, 존재하는 다음 영상을 재생합니다.
        is_remote = video_path.startswith(("http://", "https://"))
        if not is_remote and not os.path.exists(video_path):
            print(f"⚠️ 파일을 찾을 수 없습니다: {video_path}")
            n = len(self.playlist)
            for step in range(1, n):
                cand = (self.current_index + step) % n
                if os.path.exists(self.playlist[cand]):
                    self.show_osd(f"⚠️ 파일이 없어 건너뜁니다: {os.path.basename(video_path)[:40]}", duration_sec=3.0)
                    self.current_index = cand
                    return self.play_current_video()
            self.show_osd("❌ 재생목록의 파일을 찾을 수 없습니다.", duration_sec=4.0)
            return False

        # 최근 재생 기록에 추가
        history_cache.add(video_path)

        # 새 영상 시작 시 A-B 구간 반복 리셋
        if start_position_ns == 0:
            self.ab_repeat_a = None
            self.ab_repeat_b = None
            self.is_ab_repeat_active = False
            if getattr(self, "ab_badge", None):
                self.ab_badge.hide()

        # [하드웨어 적합성 검사 (SW Fallback 우선)]
        if os.path.exists(video_path):
            is_supported, reason = self.check_video_hw_support(video_path)
            if not is_supported:
                print(f"ℹ️ [코덱 상태] {os.path.basename(video_path)}: {reason} (소프트웨어 디코딩으로 즉시 재생합니다)")
                if "AV1" in reason.upper():
                    self.show_osd("⚠️ AV1 코덱: Jetson NVDEC 미지원 (H.264/H.265 포맷 권장)", duration_sec=4.0)
        
        if getattr(self, "yt_loading_box", None):
            self.hide_yt_loading()
        if getattr(self, "placeholder_box", None):
            self.placeholder_box.hide()

        if start_position_ns == 0:
            # 이어보기 체크 (이전 시청 위치가 있으면 복원)
            saved_pos_ns, saved_dur_ns = resume_cache.get(video_path)
            if saved_pos_ns > 0:
                start_position_ns = saved_pos_ns
                self.show_osd(f"⏱️ 이어서 재생: {self.format_time(saved_pos_ns)}")
                print(f"⏱️ [이어보기] {self.format_time(saved_pos_ns)} 지점부터 재생합니다.")

            abs_root = os.path.abspath(self.input_path) if (self.input_path and os.path.isdir(self.input_path)) else None
            is_net_stream = video_path.startswith("http://") or video_path.startswith("https://")
            if is_net_stream:
                disp = "▶ YouTube / 온라인 스트림"
            elif abs_root:
                rel = os.path.relpath(video_path, abs_root)
                disp = rel if not rel.startswith("..") else os.path.basename(video_path)
            else:
                disp = os.path.basename(video_path)
            print(f"\n▶ [{self.current_index + 1}/{len(self.playlist)}] 재생 중: {disp}")
            self.refresh_playlist_ui()
            self.duration_ns = 0
            self.progress_scale.set_value(0)
            self.position_label.set_text("00:00")
            self.duration_label.set_text("00:00")
            if getattr(self, "fs_progress_scale", None):
                self.fs_progress_scale.set_value(0)
            if getattr(self, "fs_position_label", None):
                self.fs_position_label.set_text("00:00")
            if getattr(self, "fs_duration_label", None):
                self.fs_duration_label.set_text("00:00")
            self.refresh_timeline_marks()
            self.decoder_names.clear()
            self.last_dropped_frames = 0
            self.last_ui_pos_sec = -1

            # 신규 영상인 경우 자막 파일 전체 탐색 및 파싱 초기화
            all_sub_files = find_all_matching_subtitles(video_path)
            self.available_subtitles = []
            for idx, s_path in enumerate(all_sub_files):
                evs = parse_subtitle_file_events(s_path)
                if evs:
                    color = get_subtitle_color(s_path, idx)
                    lbl = get_subtitle_label(s_path)
                    self.available_subtitles.append({
                        'path': s_path,
                        'label': lbl,
                        'color': color,
                        'events': evs
                    })

            self.active_subtitle_indices = set()
            if self.available_subtitles:
                if getattr(self, "single_sub_mode", True):
                    # 기본 1개(한국어 우선)만 활성화하여 화면 가림 방지
                    self.active_subtitle_indices = {0}
                    self.has_subtitles = True
                    self.subtitles_enabled = True
                    print(f"💬 [자막 자동 활성화] {self.available_subtitles[0]['label']} (다중 자막 메뉴에서 추가 선택 가능)")
                else:
                    self.active_subtitle_indices = set(range(len(self.available_subtitles)))
                    self.has_subtitles = True
                    self.subtitles_enabled = True
                    print(f"💬 [다중 자막 자동 활성화 ({len(self.available_subtitles)}개)] " + ", ".join([s['label'] for s in self.available_subtitles]))
            else:
                self.has_subtitles = False

        self.pending_seek_ns = start_position_ns
        is_net_stream = video_path.startswith("http://") or video_path.startswith("https://")
        if is_net_stream:
            video_uri = video_path
        else:
            video_uri = f"file://{pathname2url(os.path.abspath(video_path))}"
        
        # [핵심] 기존 파이프라인 및 버스 시그널 감시 완전 해제 후 NULL 처리 (EGL Surface/VIC 락 세척)
        if self.bus is not None:
            try:
                self.bus.remove_signal_watch()
            except Exception:
                pass
            self.bus = None

        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

        # 신규 playbin 파이프라인 생성
        self.subtitle_overlays = []
        self.n_embedded_text = 0
        self.pipeline = Gst.ElementFactory.make("playbin", "player")

        # 젯슨 HW 디코더 동적 속성 설정을 위한 deep-element-added 시그널 연결
        self.pipeline.connect("deep-element-added", self.on_deep_element_added)
        self.pipeline.connect("source-setup", self.on_source_setup)

        # 0x01 (video) + 0x02 (audio) + 0x04 (text/subtitles) + 0x10 (soft-volume) = 0x00000017
        self.pipeline.set_property("flags", 0x00000017)

        # 활성화된 자막 병합 파일 준비 및 suburi 설정
        active_tracks = []
        for idx in sorted(list(self.active_subtitle_indices)):
            if 0 <= idx < len(self.available_subtitles):
                sub = self.available_subtitles[idx]
                active_tracks.append((sub['label'], sub['color'], sub['events']))

        if active_tracks and self.subtitles_enabled:
            merged_file = generate_merged_subtitle_file(
                active_tracks, video_path,
                font_scale=self.subtitle_font_scale,
                offset_ms=self.subtitle_offset_ms
            )
            if merged_file:
                self.current_suburi = f"file://{pathname2url(os.path.abspath(merged_file))}"
                self.pipeline.set_property("suburi", self.current_suburi)
                if self.pipeline.find_property("subtitle-font-desc"):
                    self.pipeline.set_property("subtitle-font-desc", self.get_current_subtitle_font_desc())
                if self.pipeline.find_property("subtitle-encoding"):
                    self.pipeline.set_property("subtitle-encoding", "UTF-8")
                selected_labels = [t[0] for t in active_tracks]
                sync_info = f" / 싱크 {self.subtitle_offset_ms/1000:+.1f}s" if self.subtitle_offset_ms != 0 else ""
                print(f"💬 [다중 자막 로드 완료 ({len(active_tracks)}개 / 크기 {int(self.subtitle_font_scale*100)}%{sync_info})] " + ", ".join(selected_labels))
            else:
                self.current_suburi = None
        else:
            self.current_suburi = None

        # Totem 공식 네이티브 GTK OpenGL 비디오 싱크 할당 (60Hz V-Sync 완벽 일치 & 4K 1:1 선명도 보장)
        # 배속 재생 시 지연 프레임으로 인한 파이프라인 정체를 방지하기 위해 qos=True 및 max-lateness=50ms 설정
        if self.video_sink:
            if self.video_sink.find_property("sync"):
                self.video_sink.set_property("sync", True)
            if self.video_sink.find_property("qos"):
                self.video_sink.set_property("qos", True)
            if self.video_sink.find_property("max-lateness"):
                self.video_sink.set_property("max-lateness", 50 * Gst.MSECOND)
            self.pipeline.set_property("video-sink", self.video_sink)

        # scaletempo가 포함된 커스텀 오디오 싱크 bin 생성 (배속 재생 시 끊김 및 음정 왜곡 없는 완벽한 사운드 보장)
        audio_bin = Gst.Bin.new("audio_sink_bin")
        aconv = Gst.ElementFactory.make("audioconvert", "aconv")
        scaletempo = Gst.ElementFactory.make("scaletempo", "scaletempo")
        aresample = Gst.ElementFactory.make("audioresample", "aresample")
        asink = Gst.ElementFactory.make("autoaudiosink", "asink")
        if not asink:
            asink = Gst.ElementFactory.make("fakesink", "asink")
        if asink and asink.find_property("sync"):
            asink.set_property("sync", True)
        self.current_asink = asink
        if asink and asink.find_property("ts-offset") and self.av_sync_offset_ms != 0:
            asink.set_property("ts-offset", self.av_sync_offset_ms * 1_000_000)

        if aconv and scaletempo and aresample and asink:
            audio_bin.add(aconv)
            audio_bin.add(scaletempo)
            audio_bin.add(aresample)
            audio_bin.add(asink)
            aconv.link(scaletempo)
            scaletempo.link(aresample)
            aresample.link(asink)

            pad = aconv.get_static_pad("sink")
            ghost_pad = Gst.GhostPad.new("sink", pad)
            ghost_pad.set_active(True)
            audio_bin.add_pad(ghost_pad)
            self.pipeline.set_property("audio-sink", audio_bin)
        elif asink:
            self.pipeline.set_property("audio-sink", asink)

        # 버스 이벤트 연결
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.enable_sync_message_emission()
        self.bus.connect("sync-message::element", self.on_sync_message)
        self.bus.connect("message", self.on_bus_message)

        # URI 속성 갱신 후 플레이 시작
        self.pipeline.set_property("uri", video_uri)
        self.pipeline.set_property("volume", self.volume_scale.get_value() / 100.0)

        if not self.subtitles_enabled or not active_tracks:
            self.pipeline.set_property("current-text", -1)

        self.update_subtitle_button_ui()
        self.update_speed_button_ui()

        # 재생 중간 위치에서 자막을 재로드할 경우, 비디오/오디오/자막 스트림의 완벽한 Preroll을 위해
        # PAUSED 상태로 진입 후 ASYNC_DONE에서 정밀 Seek를 수행하고 PLAYING으로 전환합니다.
        if self.pending_seek_ns > 0:
            self.pipeline.set_state(Gst.State.PAUSED)
        else:
            self.pipeline.set_state(Gst.State.PLAYING)
            
        self.is_playing = True
        self.play_button.set_label("Ⅱ")
        if getattr(self, "fs_play_button", None):
            self.fs_play_button.set_label("Ⅱ")
        
        return False

    def on_sync_message(self, bus, message):
        """VideoOverlay 인터페이스가 필요한 fallback 싱크를 위한 창 핸들 연결"""
        is_prepare_handle = False
        if hasattr(GstVideo, "is_video_overlay_prepare_window_handle_message"):
            is_prepare_handle = GstVideo.is_video_overlay_prepare_window_handle_message(message)
        
        if not is_prepare_handle and message.get_structure():
            is_prepare_handle = (message.get_structure().get_name() == "prepare-window-handle")

        if is_prepare_handle:
            target_window = getattr(self, "video_widget", None)
            gdk_win = target_window.get_window() if target_window else self.get_window()
            if gdk_win:
                xid = None
                if hasattr(gdk_win, "get_xid"):
                    xid = gdk_win.get_xid()
                elif hasattr(GdkX11, "X11Window") and hasattr(GdkX11.X11Window, "get_xid"):
                    xid = GdkX11.X11Window.get_xid(gdk_win)
                if xid:
                    if isinstance(message.src, GstVideo.VideoOverlay) or hasattr(message.src, "set_window_handle"):
                        message.src.set_window_handle(xid)

    def on_bus_message(self, bus, message):
        """재생 완료(EOS) 및 에러 메시지 처리"""
        has_current = bool(self.playlist) and 0 <= self.current_index < len(self.playlist)
        if message.type == Gst.MessageType.EOS:
            if not has_current:
                return
            self.retry_counts.pop(self.playlist[self.current_index], None)
            # 재생 완료: 이어보기 위치를 지우고 시청 완료(✓)로 표시
            if has_current:
                resume_cache.mark_completed(self.playlist[self.current_index], self.duration_ns)
                resume_cache.save()

            if self.play_queue:
                # 사용자가 지정한 "다음에 재생" 대기열이 반복 모드보다 우선합니다.
                self.play_next_video()
            elif self.repeat_mode == "one" or self.is_single_file_mode:
                print("🔄 1곡 반복: 처음부터 다시 재생합니다.")
                GLib.timeout_add(10, self.play_current_video, 0)
            elif self.repeat_mode == "shuffle" and len(self.playlist) > 1:
                next_idx = self.current_index
                while next_idx == self.current_index:
                    next_idx = random.randint(0, len(self.playlist) - 1)
                self.current_index = next_idx
                GLib.timeout_add(50, self.play_current_video, 0)
            elif self.repeat_mode == "none":
                if self.current_index + 1 < len(self.playlist):
                    self.current_index += 1
                    GLib.timeout_add(50, self.play_current_video, 0)
                else:
                    print("⏹ 모든 영상 재생 완료 (순차 재생 정지).")
                    self.toggle_play_pause()
            else:
                self.play_next_video()
            
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"❌ 재생 중 에러 발생: {err}")
            if debug:
                print(f"   GStreamer: {debug}")
            if not has_current:
                return
            path = self.playlist[self.current_index]
            name = os.path.basename(path)[:40]
            retries = self.retry_counts.get(path, 0)
            if retries < self.max_retries:
                self.retry_counts[path] = retries + 1
                print(f"🔄 재생 파이프라인 재시도 ({retries + 1}/{self.max_retries})")
                self.show_osd(f"⚠️ 재생 오류 — 다시 시도 중 ({retries + 1}/{self.max_retries})", duration_sec=2.5)
                GLib.timeout_add(250, self.play_current_video)
            elif self.is_single_file_mode or len(self.playlist) <= 1:
                print("⏹ 반복 오류로 재생을 중단합니다. 원본과 디코더 로그를 확인하세요.")
                self.show_osd(f"❌ 재생할 수 없는 영상입니다: {name}", duration_sec=5.0)
                self.pipeline.set_state(Gst.State.PAUSED)
            else:
                print("⏭ 반복 오류 항목을 건너뜁니다.")
                self.show_osd(f"⏭ 재생 실패로 건너뜁니다: {name}", duration_sec=3.5)
                self.play_next_video()

        elif message.type == Gst.MessageType.ASYNC_DONE:
            self._detect_embedded_subtitles()
            if getattr(self, "pending_seek_ns", 0) > 0 and self.pipeline:
                seek_ns = self.pending_seek_ns
                self.pending_seek_ns = 0
                self.rate_applied_on_preroll = True
                self.pipeline.seek(
                    self.playback_rate,
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    Gst.SeekType.SET,
                    seek_ns,
                    Gst.SeekType.NONE,
                    -1
                )
                self.pipeline.set_state(Gst.State.PLAYING)
            elif not getattr(self, "rate_applied_on_preroll", False) and getattr(self, "playback_rate", 1.0) != 1.0 and self.pipeline:
                self.rate_applied_on_preroll = True
                self.pipeline.seek(
                    self.playback_rate,
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    Gst.SeekType.SET,
                    0,
                    Gst.SeekType.NONE,
                    -1
                )

        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self.pipeline:
            _old_state, new_state, _pending = message.parse_state_changed()
            self.is_playing = new_state == Gst.State.PLAYING
            lbl = "Ⅱ" if self.is_playing else "▶"
            self.play_button.set_label(lbl)
            if getattr(self, "fs_play_button", None):
                self.fs_play_button.set_label(lbl)

    def seek_relative(self, offset_seconds):
        """현재 재생 위치를 기준으로 지정된 초만큼 앞/뒤로 이동합니다."""
        if not self.pipeline:
            return
            
        success, position = self.pipeline.query_position(Gst.Format.TIME)
        if not success:
            print("⚠️ 현재 재생 위치를 확인할 수 없어 탐색에 실패했습니다.")
            return

        target_ns = position + (offset_seconds * Gst.SECOND)
        if target_ns < 0:
            target_ns = 0
        if self.duration_ns > 0 and target_ns > self.duration_ns:
            target_ns = self.duration_ns

        self.last_known_pos_ns = target_ns
        res = self.pipeline.seek(
            self.playback_rate,
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            Gst.SeekType.SET,
            target_ns,
            Gst.SeekType.NONE,
            -1
        )
        if not res:
            print("⚠️ 탐색 실패로 파이프라인을 재구축합니다.")
            self.play_current_video(start_position_ns=target_ns)
            return

        direction = "앞으로" if offset_seconds > 0 else "뒤로"
        print(f"⏩ {direction} {abs(offset_seconds)}초 이동 (현재 위치: {target_ns / Gst.SECOND:.1f}초)")
        direction_symbol = "⏩ +" if offset_seconds > 0 else "⏪ -"
        cur_str = self.format_time(target_ns)
        dur_str = f" / {self.format_time(self.duration_ns)}" if self.duration_ns > 0 else ""
        self.show_osd(f"{direction_symbol}{abs(offset_seconds)}초 ({cur_str}{dur_str})")

    def toggle_play_pause(self):
        """일시 정지 / 재생 상태를 전환합니다."""
        if not self.pipeline:
            return
            
        if self.is_playing:
            self.pipeline.set_state(Gst.State.PAUSED)
            self.is_playing = False
            self.play_button.set_label("▶")
            if getattr(self, "fs_play_button", None):
                self.fs_play_button.set_label("▶")
            self.show_osd("⏸ 일시 정지")
            print("⏸ 일시 정지")
        else:
            self.pipeline.set_state(Gst.State.PLAYING)
            self.is_playing = True
            self.play_button.set_label("Ⅱ")
            if getattr(self, "fs_play_button", None):
                self.fs_play_button.set_label("Ⅱ")
            self.show_osd("▶ 재생")
            print("▶ 다시 재생")

    def play_next_video(self):
        """다음 영상으로 전환합니다."""
        if not self.playlist:
            return
        queued_idx = self.pop_queued_index()
        if queued_idx is not None:
            self.current_index = queued_idx
            print("⏭ 대기열의 다음 영상을 재생합니다.")
            GLib.timeout_add(50, self.play_current_video, 0)
        elif self.is_single_file_mode:
            GLib.timeout_add(10, self.play_current_video, 0)
        elif self.repeat_mode == "shuffle" and len(self.playlist) > 1:
            next_idx = self.current_index
            while next_idx == self.current_index:
                next_idx = random.randint(0, len(self.playlist) - 1)
            self.current_index = next_idx
            GLib.timeout_add(50, self.play_current_video, 0)
        else:
            self.current_index = (self.current_index + 1) % len(self.playlist)
            print("⏭ 다음 영상으로 넘어갑니다.")
            GLib.timeout_add(50, self.play_current_video, 0)

    def play_prev_video(self):
        """이전 영상으로 전환합니다."""
        if not self.playlist:
            return
        if self.is_single_file_mode:
            GLib.timeout_add(10, self.play_current_video, 0)
        elif self.repeat_mode == "shuffle" and len(self.playlist) > 1:
            prev_idx = self.current_index
            while prev_idx == self.current_index:
                prev_idx = random.randint(0, len(self.playlist) - 1)
            self.current_index = prev_idx
            GLib.timeout_add(50, self.play_current_video, 0)
        else:
            self.current_index = (self.current_index - 1 + len(self.playlist)) % len(self.playlist)
            print("⏮ 이전 영상으로 넘어갑니다.")
            GLib.timeout_add(50, self.play_current_video, 0)
