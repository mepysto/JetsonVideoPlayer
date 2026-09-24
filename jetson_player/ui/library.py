"""파일/폴더 열기, 재생목록 구성, 최근 기록, HW 적합성 검사"""
import json
import os
import subprocess
import threading
import time
from urllib.request import pathname2url
from urllib.parse import unquote

from gi.repository import GLib, Gst, GstPbutils, Gtk

from ..media.codecs import nvdec_supports
from ..library import VIDEO_EXTS, scan_video_files, sort_video_paths
from ..settings import settings
from ..storage import history_cache, hw_cache
from ..subtitles.parse import get_subtitle_color, get_subtitle_label, parse_subtitle_file_events
from ..youtube import is_youtube_url


class LibraryMixin:
    def show_history_popover(self, parent_widget=None):
        """최근 재생한 파일 및 폴더 목록을 표시하는 팝오버를 표시합니다."""
        parent = parent_widget or getattr(self, "topbar", None)
        history = history_cache.get_all()

        pop = Gtk.Popover(relative_to=parent)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title = Gtk.Label(label="🕒 최근 재생 항목", xalign=0)
        title.get_style_context().add_class("popover-title")
        box.pack_start(title, False, False, 2)

        if not history:
            empty = Gtk.Label(label="최근 재생 기록이 없습니다.", xalign=0)
            empty.get_style_context().add_class("muted")
            box.pack_start(empty, False, False, 6)
        else:
            scroll = Gtk.ScrolledWindow()
            scroll.set_min_content_height(160)
            scroll.set_min_content_width(280)
            list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            for item in history:
                icon = "📁 " if item.get("is_dir") else "🎬 "
                btn = Gtk.Button(label=f"{icon}{item['title']}")
                btn.set_tooltip_text(item['path'])
                btn.get_style_context().add_class("tree-tool-btn")
                btn.connect("clicked", lambda _b, p=item['path']: (pop.popdown(), self.load_target_path(p)))
                list_box.pack_start(btn, False, False, 0)
            scroll.add(list_box)
            box.pack_start(scroll, True, True, 0)

        box.show_all()
        pop.add(box)
        pop.popup()

    def load_target_path(self, path):
        """파일 또는 폴더 경로를 로드하여 즉시 재생합니다 (최근 재생 목록에서 사용)."""
        if not path or not os.path.exists(path):
            self.show_osd("경로가 존재하지 않습니다.")
            return
        # load_path가 input_path/단일 파일 모드/재생목록 UI를 일관되게 갱신합니다.
        self.load_path(os.path.abspath(path))

    def open_file_dialog(self):
        """파일 선택 다이얼로그를 띄워 새 동영상을 선택 및 재생합니다."""
        dialog = Gtk.FileChooserDialog(
            title="동영상 파일 열기",
            parent=self,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )
        dialog.set_select_multiple(True)

        filter_video = Gtk.FileFilter()
        filter_video.set_name("동영상 파일")
        for ext in ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.webm", "*.ts", "*.m4v"]:
            filter_video.add_pattern(ext)
            filter_video.add_pattern(ext.upper())
        dialog.add_filter(filter_video)

        filter_all = Gtk.FileFilter()
        filter_all.set_name("모든 파일")
        filter_all.add_pattern("*")
        dialog.add_filter(filter_all)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            filenames = dialog.get_filenames()
            dialog.destroy()
            if filenames:
                self.load_files(filenames)
        else:
            dialog.destroy()

    def open_folder_dialog(self):
        """폴더 선택 다이얼로그를 띄워 폴더 내 영상들을 재생목록으로 구성합니다."""
        dialog = Gtk.FileChooserDialog(
            title="동영상 폴더 열기",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            folder = dialog.get_filename()
            dialog.destroy()
            if folder:
                self.load_path(folder)
        else:
            dialog.destroy()

    def load_path(self, input_path):
        """새로운 파일 또는 폴더 경로를 로드하여 즉시 재생을 시작합니다."""
        prev_input, prev_single = self.input_path, self.is_single_file_mode
        self.input_path = input_path
        if not self.build_playlist():
            # 기존 재생목록을 유지하고 앱을 종료하지 않습니다.
            self.input_path, self.is_single_file_mode = prev_input, prev_single
            self.show_osd("⚠️ 재생 가능한 영상이 없는 폴더입니다.", duration_sec=2.5)
            return
        self.populate_playlist_tree()
        self.refresh_playlist_ui()
        if self.playlist:
            self.current_index = 0
            if getattr(self, "placeholder_box", None):
                self.placeholder_box.hide()
            self.play_current_video()

    def load_files(self, files):
        """다중 파일 목록을 재생목록에 추가하고 재생을 시작합니다."""
        if not files:
            return
        valid_files = [f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXTS]
        if not valid_files:
            return
        self.playlist = sort_video_paths(valid_files, settings.get("playlist_sort"))
        self.input_path = os.path.dirname(valid_files[0]) if len(valid_files) > 1 else valid_files[0]
        self.current_index = 0
        self.is_single_file_mode = (len(valid_files) == 1)
        self.populate_playlist_tree()
        self.refresh_playlist_ui()
        if getattr(self, "placeholder_box", None):
            self.placeholder_box.hide()
        self.play_current_video()

    def on_drag_data_received(self, widget, context, x, y, data, info, time):
        """파일 탐색기에서 드롭된 파일/폴더 또는 유튜브 링크를 처리합니다."""
        # 1. 유튜브 링크 드롭 감지
        try:
            raw_text = data.get_text()
            if raw_text and is_youtube_url(raw_text):
                context.finish(True, False, time)
                self.start_youtube_stream(raw_text, quality="best")
                return
        except Exception:
            pass

        uris = data.get_uris()
        if not uris:
            context.finish(False, False, time)
            return

        # URI 형태의 유튜브 링크 검사
        for u in uris:
            if is_youtube_url(u):
                context.finish(True, False, time)
                self.start_youtube_stream(u, quality="best")
                return

        paths = []
        for uri in uris:
            if uri.startswith("file://"):
                p = unquote(uri[7:])
                if os.path.exists(p):
                    paths.append(p)

        if not paths:
            context.finish(False, False, time)
            return

        first = paths[0]
        sub_exts = {'.srt', '.smi', '.vtt', '.ass', '.ssa', '.sub'}
        ext = os.path.splitext(first)[1].lower()

        # 자막 파일이 드롭된 경우: 현재 재생 영상에 자막 추가 적용
        if ext in sub_exts:
            evs = parse_subtitle_file_events(first)
            if evs:
                idx = len(self.available_subtitles)
                color = get_subtitle_color(first, idx)
                lbl = get_subtitle_label(first)
                self.available_subtitles.append(self.make_subtitle_entry(first, lbl, color, evs))
                self.active_subtitle_indices.add(idx)
                self.has_subtitles = True
                self.subtitles_enabled = True
                self.schedule_subtitles_reload()
                self.show_osd(f"💬 자막 추가됨: {lbl}")
                print(f"💬 드래그로 자막 추가: {first}")
            context.finish(True, False, time)
            return

        # 디렉토리가 드롭된 경우
        if os.path.isdir(first):
            self.load_path(first)
            context.finish(True, False, time)
            return

        # 동영상 파일들이 드롭된 경우
        video_files = [p for p in paths if os.path.splitext(p)[1].lower() in VIDEO_EXTS]
        if video_files:
            self.load_files(video_files)
            context.finish(True, False, time)
            return

        context.finish(False, False, time)

    def check_video_hw_support(self, file_path):
        """NVDEC 하드웨어 디코딩 가능 여부를 (지원 여부, 사유)로 반환합니다.

        지원 여부가 None이면 판별할 수 없다는 뜻입니다 (ffprobe/Discoverer 실패) — 이 경우 호출하는 쪽은
        하드웨어 경로를 먼저 시도합니다. 결과는 파일 크기/수정 시각 기준으로 캐시합니다.
        """
        cached = hw_cache.get(file_path)
        if cached is not None:
            return cached

        codec, pix_fmt, profile = None, "", ""
        try:
            cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
                   "-show_entries", "stream=codec_name,pix_fmt,profile", "-of", "json", file_path]
            data = json.loads(subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=15))
            if not data.get("streams"):
                res = (False, "비디오 스트림 없음")
                hw_cache.set(file_path, res[0], res[1])
                return res
            stream = data["streams"][0]
            codec, pix_fmt, profile = stream.get("codec_name", ""), stream.get("pix_fmt", ""), stream.get("profile", "")
        except Exception:
            # ffprobe가 없거나 실패하면 GStreamer Discoverer로 코덱만 확인
            try:
                uri = f"file://{pathname2url(os.path.abspath(file_path))}"
                info = GstPbutils.Discoverer.new(3 * Gst.SECOND).discover_uri(uri)
                streams = info.get_video_streams()
                if streams:
                    caps = streams[0].get_caps().to_string().lower()
                    codec = caps.split(",")[0].replace("video/x-", "")
                    depth = "10" if "bit-depth-luma=(uint)10" in caps else ""
                    chroma = "444" if "4:4:4" in caps else ("422" if "4:2:2" in caps else "420")
                    pix_fmt = f"yuv{chroma}p{depth}le" if depth else f"yuv{chroma}p"
            except Exception:
                pass
        if not codec:
            return None, "코덱 분석 실패"
        res = nvdec_supports(codec, pix_fmt, profile)
        hw_cache.set(file_path, res[0], res[1])
        return res

    def build_playlist(self):
        """입력값을 분석하여 재생 목록을 구성합니다 (같은 폴더의 _h265.mp4 변환본이 있으면 우선 사용).
        성공하면 True, 경로가 잘못되었거나 영상이 없으면 False를 반환합니다."""
        abs_path = os.path.abspath(self.input_path)
        
        raw_playlist = []
        if os.path.isdir(abs_path):
            self.is_single_file_mode = False
            try:
                raw_playlist = scan_video_files(abs_path)
            except Exception as e:
                print(f"❌ 디렉토리 읽기 실패 ({abs_path}): {e}")
                return False
            if not raw_playlist:
                print(f"❌ 에러: [{self.input_path}] 폴더 내에 재생 가능한 영상 파일이 없습니다.")
                return False

        elif os.path.isfile(abs_path):
            self.is_single_file_mode = True
            raw_playlist.append(abs_path)
        else:
            print(f"❌ 에러: [{self.input_path}] 존재하지 않는 파일이거나 올바르지 않은 경로입니다.")
            return False

        # [초고속 시작 최적화] 시작 시 모든 파일에 대한 무거운 ffprobe 검사를 건너뛰고,
        # 기존 H.265 변환본이 있는 경우에만 빠르게 우선 매핑하여 0.05초 만에 재생목록을 완성합니다.
        # 하드웨어 재생 적합성 검사는 현재 재생할 영상에 대해 On-Demand로 즉시 수행되고,
        # 나머지 영상들은 재생 중 백그라운드 스레드에서 점진적으로 검사/캐싱됩니다.
        self.playlist = []
        processed_set = set()
        raw_set = set(raw_playlist)
        for path in raw_playlist:
            if not os.path.exists(path) or path in processed_set:
                continue

            dir_name = os.path.dirname(path)
            base_name = os.path.basename(path)
            name_no_ext, _ext = os.path.splitext(base_name)

            final_path = path
            # 동일 폴더에 이미 _h265.mp4 변환본이 존재하는 경우 변환본을 채택
            if not name_no_ext.endswith("_h265"):
                target_h265 = os.path.join(dir_name, f"{name_no_ext}_h265.mp4")
                if target_h265 in raw_set or os.path.exists(target_h265):
                    final_path = target_h265
                    processed_set.add(path)

            if final_path not in self.playlist:
                self.playlist.append(final_path)
                processed_set.add(final_path)

        self.playlist = sort_video_paths(self.playlist, settings.get("playlist_sort"))
        mode_str = "단일 파일 반복 모드" if self.is_single_file_mode else "폴더 순환 모드"
        print(f"📂 [{mode_str}] 총 {len(self.playlist)}개의 영상을 로드했습니다.")
        for idx, path in enumerate(self.playlist):
            disp = os.path.relpath(path, abs_path) if not self.is_single_file_mode else os.path.basename(path)
            print(f"   [{idx}] {disp}")
        return True

    def start_background_hw_checker(self):
        """백그라운드에서 재생목록 파일들의 하드웨어 가속 적합성을 점진적으로 검사하고 캐싱합니다."""
        if getattr(self, "_bg_checker_started", False):
            return
        self._bg_checker_started = True
        t = threading.Thread(target=self._background_hw_worker, daemon=True)
        t.start()

    def _background_hw_worker(self):
        # 첫 영상이 시작되고 UI가 완전히 렌더링될 때까지 1.5초 대기
        time.sleep(1.5)
        for idx in range(len(self.playlist)):
            if getattr(self, "is_destroyed", False):
                break
            if idx >= len(self.playlist):
                break
            path = self.playlist[idx]
            if not os.path.exists(path):
                continue

            # 캐시가 이미 존재하면 스킵 (불필요한 작업 방지)
            cached = hw_cache.get(path)
            if cached is None:
                is_supported, _reason = self.check_video_hw_support(path)
                # 동일 폴더에 이미 _h265.mp4가 존재하는 경우 메인 스레드에 경로 교체 요청
                if not is_supported:
                    dir_name = os.path.dirname(path)
                    name_no_ext, _ext = os.path.splitext(os.path.basename(path))
                    target_h265 = os.path.join(dir_name, f"{name_no_ext}_h265.mp4")
                    if os.path.exists(target_h265):
                        GLib.idle_add(self._apply_background_h265_path, path, target_h265)
                # 현재 영상 재생 성능에 영향을 주지 않도록 파일 간 0.05초 대기
                time.sleep(0.05)

        hw_cache.save()

    def _apply_background_h265_path(self, original_path, new_path):
        # 검사 도중 재생목록이 정렬/교체되었을 수 있으므로 인덱스가 아니라 원래 경로로 찾습니다.
        if original_path in self.playlist and os.path.exists(new_path):
            idx = self.playlist.index(original_path)
            self.playlist[idx] = new_path
            self.update_playlist_item_ui(idx, new_path)
        return False
