#!/usr/bin/env python3
import sys
import os
import glob
import subprocess
import shutil
import json
import re
import hashlib
import gi
from urllib.request import pathname2url

# 환경 변수 자동 설정 (cannot open display 에러 방지)
if "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":0"
if "XDG_RUNTIME_DIR" not in os.environ:
    os.environ["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"

# 필요한 GStreamer 및 GTK 컴포넌트 로드
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GdkX11', '3.0')
from gi.repository import Gst, Gtk, Gdk, GstVideo, GLib, GdkX11

def enable_x11_compositor_bypass(gdk_window):
    """
    GNOME Mutter 윈도우 컴포지터의 중간 재합성으로 인한 프레임 지터를 차단하기 위해
    X11 _NET_WM_BYPASS_COMPOSITOR 힌트를 지정하여 Direct GPU 스캔아웃을 활성화합니다.
    """
    try:
        xid = None
        if hasattr(gdk_window, "get_xid"):
            xid = gdk_window.get_xid()
        elif hasattr(GdkX11, "X11Window") and hasattr(GdkX11.X11Window, "get_xid"):
            xid = GdkX11.X11Window.get_xid(gdk_window)
        if xid:
            subprocess.run(
                ["xprop", "-id", str(xid), "-f", "_NET_WM_BYPASS_COMPOSITOR", "32c", "-set", "_NET_WM_BYPASS_COMPOSITOR", "1"],
                capture_output=True, check=False
            )
    except Exception:
        pass

def optimize_gstreamer_ranks():
    """
    Jetson 하드웨어 디코더(nvv4l2decoder)를 H.264/H.265 및 AV1 코덱에 우선 할당하여 
    4K 60fps 단일 영상 재생 시 CPU 병목으로 인한 화면 끊김(Stuttering)을 완벽히 방지합니다.
    JetPack 드라이버 에러(NvBufSurfTransform -1)가 발생하는 VP9 10-bit HDR 영상만 SW 디코더(vp9dec)로 우회합니다.
    """
    registry = Gst.Registry.get()
    
    # 1. Jetson 하드웨어 디코더 존재 여부 감지
    hw_decoder = registry.find_feature("nvv4l2decoder", Gst.ElementFactory.__gtype__)
    
    if hw_decoder:
        # Jetson 하드웨어 디코더 및 변환기 우위 설정 (PRIMARY + 1000)
        hw_elements = ["nvv4l2decoder", "nvvidconv"]
        for name in hw_elements:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY + 1000)
        
        # AV1/H264/H265/VP9 스트림 파서 랭크 상향 (프레임 경계 추출 보장)
        parsers = ["av1parse", "h264parse", "h265parse", "vp9parse"]
        for name in parsers:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY + 1500)

        # 소프트웨어 디코더는 기본 rank를 유지합니다. 하드웨어를 우선하되 특정
        # 프로파일/드라이버 오류에서는 GStreamer가 안전하게 fallback할 수 있어야 합니다.

        # CPU 소프트웨어 비디오 변환기/스케일러 랭크 유지 (Standard Format Conversion 허용)
        for name in ["videoconvert", "videoscale"]:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY)

        print("⚡ [하드웨어 가속 60 FPS 최적화] nvv4l2decoder HW 가속 및 60 FPS 전용 파이프라인 무결 적용 완료.")
    else:
        print("ℹ️ [소프트웨어 디코딩] Jetson HW 디코더(nvv4l2decoder)가 감지되지 않아 기본 디코더를 유지합니다.")

SUBTITLE_COLORS = ["#FFFFFF", "#E9FF5B", "#80D8FF", "#FF80AB", "#B388FF", "#69F0AE"]

def ms_to_srt_time(ms):
    """밀리초(ms)를 SRT 타임코드(HH:MM:SS,mmm) 포맷으로 변환합니다."""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    ms %= 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"

def srt_time_to_ms(time_str):
    """00:01:23,456 또는 00:01:23.456 형태의 타임코드를 밀리초(ms)로 변환합니다."""
    time_str = time_str.strip().replace(',', '.')
    parts = time_str.split(':')
    try:
        if len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            s_parts = parts[2].split('.')
            s = int(s_parts[0])
            ms = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
            return (h * 3600 + m * 60 + s) * 1000 + ms
        elif len(parts) == 2:
            m = int(parts[0])
            s_parts = parts[1].split('.')
            s = int(s_parts[0])
            ms = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
            return (m * 60 + s) * 1000 + ms
    except Exception:
        pass
    return 0

def read_subtitle_text(file_path):
    """다양한 인코딩(UTF-8, CP949, EUC-KR 등)을 자동 감지하여 자막 텍스트를 로드합니다."""
    encodings = ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr', 'utf-16', 'latin-1']
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                content = f.read()
                return content, enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(file_path, 'r', encoding='latin-1', errors='replace') as f:
        return f.read(), 'latin-1'

def parse_smi_to_events(content):
    """SAMI (.smi) 텍스트를 [(start_ms, end_ms, text), ...] 목록으로 파싱합니다."""
    sync_pattern = re.compile(r'<sync\s+start\s*=\s*["\']?(\d+)["\']?[^>]*>(.*?)(?=<sync|$)', re.IGNORECASE | re.DOTALL)
    tag_cleaner = re.compile(r'<[^>]+>')
    raw_entries = []
    for match in sync_pattern.finditer(content):
        start_ms = int(match.group(1))
        body = match.group(2)
        body = re.sub(r'<br\s*/?>', '\n', body, flags=re.IGNORECASE)
        clean = tag_cleaner.sub('', body)
        clean = clean.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"')
        clean = "\n".join([line.strip() for line in clean.splitlines() if line.strip()])
        raw_entries.append((start_ms, clean))
    
    events = []
    for i in range(len(raw_entries)):
        start_ms, text = raw_entries[i]
        if not text or text == '&nbsp;' or text.isspace():
            continue
        if i + 1 < len(raw_entries):
            end_ms = raw_entries[i+1][0]
            if end_ms - start_ms > 7000:
                end_ms = start_ms + 4000
        else:
            end_ms = start_ms + 4000
        if end_ms <= start_ms:
            end_ms = start_ms + 1000
        events.append((start_ms, end_ms, text))
    return events

def parse_srt_or_vtt_to_events(content):
    """SRT / WebVTT 텍스트를 [(start_ms, end_ms, text), ...] 목록으로 파싱합니다."""
    time_pat = re.compile(r'(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}|\d{1,2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}|\d{1,2}:\d{2}[,\.]\d{1,3})')
    tag_cleaner = re.compile(r'<[^>]+>')
    blocks = re.split(r'\n\s*\n', content.strip())
    events = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_match = None
        text_lines = []
        for line in lines:
            m = time_pat.search(line)
            if m:
                time_match = m
            elif time_match:
                clean = tag_cleaner.sub('', line)
                if clean:
                    text_lines.append(clean)
        if time_match and text_lines:
            start_ms = srt_time_to_ms(time_match.group(1))
            end_ms = srt_time_to_ms(time_match.group(2))
            text = "\n".join(text_lines)
            if end_ms > start_ms:
                events.append((start_ms, end_ms, text))
    return events

def parse_ass_to_events(content):
    """ASS / SSA 자막 텍스트를 [(start_ms, end_ms, text), ...] 목록으로 파싱합니다."""
    tag_cleaner = re.compile(r'\{.*?\}')
    events = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) >= 10:
            start_ms = srt_time_to_ms(parts[1])
            end_ms = srt_time_to_ms(parts[2])
            raw_text = parts[9]
            clean = tag_cleaner.sub('', raw_text)
            clean = clean.replace('\\N', '\n').replace('\\n', '\n').strip()
            if clean and end_ms > start_ms:
                events.append((start_ms, end_ms, clean))
    return events

def parse_subtitle_file_events(file_path):
    """자막 파일의 인코딩을 자동 감지하고 포맷에 맞게 파싱하여 타임라인 이벤트 목록을 반환합니다."""
    try:
        content, _enc = read_subtitle_text(file_path)
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.smi':
            return parse_smi_to_events(content)
        elif ext in ['.ass', '.ssa']:
            return parse_ass_to_events(content)
        else:
            return parse_srt_or_vtt_to_events(content)
    except Exception as e:
        print(f"⚠️ 자막 파싱 실패 ({file_path}): {e}")
        return []

def get_subtitle_label(file_path):
    """자막 파일명에서 언어 태그를 감지하여 사람이 읽기 쉬운 레이블을 생성합니다."""
    base = os.path.basename(file_path)
    stem, _ext = os.path.splitext(base)
    stem_lower = stem.lower()
    
    # 한국어
    if any(k in stem_lower for k in ['.ko', '.kor', '.kr', '_ko', '_kor', '_kr', '.korean', '한국어', '한글']):
        return f"🇰🇷 한국어 ({base})"
    # 영어
    elif any(k in stem_lower for k in ['.en', '.eng', '_en', '_eng', '.english', '영어', '영문']):
        return f"🇺🇸 영어 ({base})"
    # 일본어
    elif any(k in stem_lower for k in ['.ja', '.jpn', '.jp', '_ja', '_jpn', '.japanese', '일본어', '일어']):
        return f"🇯🇵 일본어 ({base})"
    # 중국어
    elif any(k in stem_lower for k in ['.zh', '.chi', '.zho', '_zh', '_chi', '.chinese', '중국어', '중문', '.cmn']):
        return f"🇨🇳 중국어 ({base})"
    # 스페인어
    elif any(k in stem_lower for k in ['.es', '.spa', '_es', '_spa', '.spanish', '스페인어']):
        return f"🇪🇸 스페인어 ({base})"
    # 프랑스어
    elif any(k in stem_lower for k in ['.fr', '.fre', '.fra', '_fr', '_fre', '.french', '프랑스어']):
        return f"🇫🇷 프랑스어 ({base})"
    # 독일어
    elif any(k in stem_lower for k in ['.de', '.ger', '.deu', '_de', '_ger', '.german', '독일어']):
        return f"🇩🇪 독일어 ({base})"
    
    return f"📄 {base}"

def find_all_matching_subtitles(video_path):
    """동영상 파일과 관련된 모든 자막 파일(.srt, .smi, .vtt, .ass, .ssa, .sub) 목록을 탐색하여 반환합니다."""
    dir_name = os.path.dirname(os.path.abspath(video_path))
    base_name = os.path.basename(video_path)
    stem, _ = os.path.splitext(base_name)
    stem_lower = stem.lower()
    sub_exts = ['.srt', '.smi', '.vtt', '.ass', '.ssa', '.sub']
    
    found_files = []
    seen = set()
    
    # 1. 동일한 파일명 (대소문자 무관)
    for ext in sub_exts:
        for c_ext in [ext, ext.upper()]:
            cand = os.path.join(dir_name, stem + c_ext)
            if os.path.isfile(cand) and cand not in seen:
                seen.add(cand)
                found_files.append(cand)
                
    # 2. 언어 태그 및 확장자 매칭
    try:
        for fname in os.listdir(dir_name):
            cand_path = os.path.join(dir_name, fname)
            if not os.path.isfile(cand_path) or cand_path in seen:
                continue
            f_lower = fname.lower()
            if any(f_lower.endswith(ext) for ext in sub_exts):
                if f_lower.startswith(stem_lower) or stem_lower in f_lower:
                    seen.add(cand_path)
                    found_files.append(cand_path)
    except Exception:
        pass
        
    # 만약 위 규칙으로 찾은 자막이 없고 디렉토리에 자막 파일이 있다면 모두 포함
    if not found_files:
        try:
            for fname in os.listdir(dir_name):
                cand_path = os.path.join(dir_name, fname)
                if os.path.isfile(cand_path) and any(fname.lower().endswith(ext) for ext in sub_exts):
                    if cand_path not in seen:
                        seen.add(cand_path)
                        found_files.append(cand_path)
        except Exception:
            pass

    # 한국어, 영어 순서가 앞으로 오도록 스마트 정렬
    def sort_key(path):
        lbl = get_subtitle_label(path)
        if "한국어" in lbl:
            return (0, path)
        if "영어" in lbl:
            return (1, path)
        if "일본어" in lbl:
            return (2, path)
        return (3, path)

    found_files.sort(key=sort_key)
    return found_files

def merge_subtitle_tracks(tracks):
    """
    여러 자막 트랙 [(label, color, events), ...]의 타임라인을 정밀 분할하여
    화면에 여러 자막이 동시에 겹침 없이 표시되도록 단일 다중 색상 SRT 문자열로 병합합니다.
    """
    if not tracks:
        return ""
        
    time_points = set()
    for _, _, events in tracks:
        for start_ms, end_ms, _ in events:
            time_points.add(start_ms)
            time_points.add(end_ms)
            
    sorted_times = sorted(list(time_points))
    if len(sorted_times) < 2:
        return ""
        
    srt_blocks = []
    is_multi = len(tracks) > 1
    
    for i in range(len(sorted_times) - 1):
        t_start = sorted_times[i]
        t_end = sorted_times[i + 1]
        if t_end <= t_start:
            continue
            
        active_lines = []
        for _label, color, events in tracks:
            for ev_start, ev_end, text in events:
                if ev_start <= t_start and ev_end >= t_end:
                    if text and not text.isspace():
                        if is_multi and color:
                            styled = f'<span color="{color}">{text}</span>'
                        else:
                            styled = text
                        active_lines.append(styled)
                    break
                    
        if active_lines:
            combined_text = "\n".join(active_lines)
            srt_blocks.append((t_start, t_end, combined_text))
            
    # 연속된 동일 텍스트 블록 병합 최적화
    merged_blocks = []
    for start, end, text in srt_blocks:
        if merged_blocks and merged_blocks[-1][1] == start and merged_blocks[-1][2] == text:
            merged_blocks[-1] = (merged_blocks[-1][0], end, text)
        else:
            merged_blocks.append((start, end, text))
            
    out = []
    for idx, (start, end, text) in enumerate(merged_blocks, 1):
        out.append(f"{idx}\n{ms_to_srt_time(start)} --> {ms_to_srt_time(end)}\n{text}\n")
        
    return "\n".join(out)

def generate_merged_subtitle_file(active_tracks, video_path):
    """
    선택된 자막 트랙들을 병합하여 임시 캐시 디렉토리에 SRT 파일로 생성하고 그 경로를 반환합니다.
    """
    if not active_tracks:
        return None
        
    cache_dir = "/tmp/jetson_subtitles"
    os.makedirs(cache_dir, exist_ok=True)
    
    track_ids = "_".join([t[0] for t in active_tracks])
    h = hashlib.md5((video_path + track_ids).encode('utf-8')).hexdigest()[:14]
    target_file = os.path.join(cache_dir, f"merged_sub_{h}.srt")
    
    srt_content = merge_subtitle_tracks(active_tracks)
    if not srt_content:
        return None
        
    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(srt_content)
        
    return target_file

class JetsonSignageFlexiblePlayer(Gtk.Window):
    def __init__(self, input_path):
        super().__init__(title="Jetson Video Player")
        
        # [필수] 하드웨어 가속 랭크 최적화 보장
        optimize_gstreamer_ranks()

        # 1. 플레이어 창 설정
        self.set_decorated(False)
        self.fullscreen()
        self.set_keep_above(True)
        self.set_default_size(1280, 720)
        
        # 이벤트 연결 (종료, 키보드 및 마우스 감지)
        self.connect("destroy", self.on_destroy)
        self.connect("key-press-event", self.on_key_press)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("motion-notify-event", self.on_mouse_motion)
        self.connect("button-press-event", self.on_window_button_press)

        # 2. 입력 경로 타입(폴더 vs 파일)을 분석하여 재생 목록 구성
        self.input_path = input_path
        self.playlist = []
        self.current_index = 0
        self.is_single_file_mode = False
        self.xid = None
        self.build_playlist()

        # UI/재생 상태
        self.is_playing = True
        self.is_fullscreen = True
        self.is_video_only = False
        self.sidebar_was_visible = True
        self.is_seeking = False
        self.duration_ns = 0
        self.playlist_rows = []
        self.decoder_names = set()
        self.video_sink = None
        self.stats_ticks = 0
        self.last_dropped_frames = 0
        self.last_ui_pos_sec = -1
        self.retry_counts = {}
        self.max_retries = 2

        # 마우스 커서 숨김 제어 상태
        self.cursor_hide_timer_id = None
        self.is_cursor_hidden = False

        # 다중 자막(Subtitle) 상태 변수 초기화
        self.subtitles_enabled = True
        self.has_subtitles = False
        self.available_subtitles = []  # list of dicts: {'path', 'label', 'color', 'events'}
        self.active_subtitle_indices = set()  # set of int indices
        self.sub_popover = None

        # 3. 비디오가 임베딩될 GtkGLSink 네이티브 OpenGL 위젯 생성 (Totem 공식 아키텍처)
        self.gtk_sink = Gst.ElementFactory.make("gtkglsink", "gtk_sink")
        if self.gtk_sink:
            self.video_sink_bin = Gst.ElementFactory.make("glsinkbin", "glsinkbin")
            self.video_sink_bin.set_property("sink", self.gtk_sink)
            self.video_widget = self.gtk_sink.get_property("widget")
            self.video_sink = self.video_sink_bin
        else:
            self.gtk_sink = Gst.ElementFactory.make("gtksink", "gtk_sink")
            self.video_widget = self.gtk_sink.get_property("widget") if self.gtk_sink else Gtk.DrawingArea()
            self.video_sink = self.gtk_sink

        self.video_widget.set_hexpand(True)
        self.video_widget.set_vexpand(True)
        self.video_widget.set_size_request(640, 480)
        self.video_widget.connect("realize", self.on_realize)

        self.build_ui()

        # 4. GStreamer 핵심 파이프라인 변수 초기화
        self.pipeline = None
        self.bus = None

        # 재생 위치와 UI 상태 갱신 (1초 주기로 최적화하여 X11 UI 경합 방지)
        self.position_timer_id = GLib.timeout_add(1000, self.update_playback_ui)

    def build_ui(self):
        """Jetson EGL 출력과 충돌하지 않는 네이티브 GTK 플레이어 UI를 구성합니다."""
        css = b"""
        window { background: #090b10; color: #f4f6fb; }
        .topbar, .controls { background: #11151d; }
        .topbar { border-bottom: 1px solid #252b36; }
        .controls { border-top: 1px solid #252b36; }
        .brand { font-size: 17px; font-weight: 700; color: #ffffff; }
        .muted { color: #8f98a8; font-size: 12px; }
        .now-playing { color: #dce2ec; font-size: 13px; }
        button { background: transparent; color: #dce2ec; border: 0; border-radius: 7px; padding: 7px 10px; }
        button:hover { background: #252b36; color: #ffffff; }
        .primary { background: #e9ff5b; color: #111318; border-radius: 20px; min-width: 28px; min-height: 28px; }
        .primary:hover { background: #f2ff91; color: #111318; }
        .sidebar { background: #0e1117; border-left: 1px solid #252b36; }
        .section-title { font-size: 15px; font-weight: 700; color: #ffffff; }
        .playlist-row { border-radius: 8px; padding: 7px; }
        .playlist-row:hover { background: #1a1f29; }
        .playlist-row-active { background: #242b35; border-left: 3px solid #e9ff5b; }
        .track-number { color: #70798a; font-size: 12px; }
        .track-title { color: #dce2ec; font-size: 13px; }
        scale trough { background: #303744; min-height: 4px; border-radius: 3px; }
        scale highlight { background: #e9ff5b; border-radius: 3px; }
        scale slider { background: #ffffff; min-width: 13px; min-height: 13px; border-radius: 7px; }
        popover { background: #131822; border: 1px solid #2a3240; border-radius: 9px; color: #f4f6fb; padding: 6px; }
        .popover-title { font-size: 13px; font-weight: 700; color: #e9ff5b; margin-bottom: 4px; }
        .sub-btn-row button { background: #1c222e; border-radius: 5px; padding: 4px 8px; font-size: 11px; }
        .sub-btn-row button:hover { background: #2a3344; }
        checkbutton { color: #dce2ec; font-size: 12px; }
        checkbutton:hover { color: #ffffff; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        self.topbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.topbar.get_style_context().add_class("topbar")
        self.topbar.set_border_width(10)
        brand = Gtk.Label(label="JETSON  /  VIDEO PLAYER")
        brand.get_style_context().add_class("brand")
        self.topbar.pack_start(brand, False, False, 4)
        self.now_playing_label = Gtk.Label(xalign=0)
        self.now_playing_label.set_ellipsize(3)
        self.now_playing_label.get_style_context().add_class("now-playing")
        self.topbar.pack_start(self.now_playing_label, True, True, 12)
        playlist_toggle = Gtk.Button(label="☷  재생목록")
        playlist_toggle.set_tooltip_text("재생목록 열기/닫기")
        playlist_toggle.connect("clicked", self.on_playlist_toggle)
        self.topbar.pack_end(playlist_toggle, False, False, 0)
        close_button = Gtk.Button(label="✕")
        close_button.set_tooltip_text("종료 (Esc)")
        close_button.connect("clicked", self.on_destroy)
        self.topbar.pack_end(close_button, False, False, 0)
        root.pack_start(self.topbar, False, False, 0)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content.pack_start(self.video_widget, True, True, 0)
        self.sidebar = self.build_playlist_panel()
        content.pack_end(self.sidebar, False, False, 0)
        root.pack_start(content, True, True, 0)

        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.controls.get_style_context().add_class("controls")
        self.controls.set_border_width(10)

        timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.position_label = Gtk.Label(label="00:00")
        self.position_label.get_style_context().add_class("muted")
        self.progress_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.progress_scale.set_draw_value(False)
        self.progress_scale.set_hexpand(True)
        self.progress_scale.connect("button-press-event", self.on_seek_start)
        self.progress_scale.connect("button-release-event", self.on_seek_end)
        self.duration_label = Gtk.Label(label="00:00")
        self.duration_label.get_style_context().add_class("muted")
        timeline.pack_start(self.position_label, False, False, 0)
        timeline.pack_start(self.progress_scale, True, True, 0)
        timeline.pack_start(self.duration_label, False, False, 0)
        self.controls.pack_start(timeline, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        prev_button = Gtk.Button(label="⏮")
        prev_button.set_tooltip_text("이전 영상 (P)")
        prev_button.connect("clicked", lambda _button: self.play_prev_video())
        self.play_button = Gtk.Button(label="Ⅱ")
        self.play_button.get_style_context().add_class("primary")
        self.play_button.set_tooltip_text("재생/일시정지 (Space)")
        self.play_button.connect("clicked", lambda _button: self.toggle_play_pause())
        next_button = Gtk.Button(label="⏭")
        next_button.set_tooltip_text("다음 영상 (N)")
        next_button.connect("clicked", lambda _button: self.play_next_video())
        rewind_button = Gtk.Button(label="↶ 10")
        rewind_button.set_tooltip_text("10초 뒤로 (←)")
        rewind_button.connect("clicked", lambda _button: self.seek_relative(-10))
        forward_button = Gtk.Button(label="10 ↷")
        forward_button.set_tooltip_text("10초 앞으로 (→)")
        forward_button.connect("clicked", lambda _button: self.seek_relative(10))
        for button in (prev_button, rewind_button, self.play_button, forward_button, next_button):
            actions.pack_start(button, False, False, 0)

        spacer = Gtk.Box()
        actions.pack_start(spacer, True, True, 0)
        volume_icon = Gtk.Label(label="◖)))")
        volume_icon.get_style_context().add_class("muted")
        actions.pack_start(volume_icon, False, False, 4)
        self.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume_scale.set_size_request(110, -1)
        self.volume_scale.set_draw_value(False)
        self.volume_scale.set_value(100)
        self.volume_scale.connect("value-changed", self.on_volume_changed)
        actions.pack_start(self.volume_scale, False, False, 0)
        self.fullscreen_button = Gtk.Button(label="⛶")
        self.fullscreen_button.set_tooltip_text("영상만 전체화면 (F)")
        self.fullscreen_button.connect("clicked", lambda _button: self.toggle_fullscreen())
        actions.pack_end(self.fullscreen_button, False, False, 0)

        self.sub_button = Gtk.Button(label="💬 자막")
        self.sub_button.set_tooltip_text("자막 켜기/끄기 (S)")
        self.sub_button.connect("clicked", self.on_sub_button_clicked)
        actions.pack_end(self.sub_button, False, False, 4)

        self.controls.pack_start(actions, False, False, 0)
        root.pack_end(self.controls, False, False, 0)

        self.refresh_playlist_ui()

    def build_playlist_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.get_style_context().add_class("sidebar")
        panel.set_size_request(310, -1)
        panel.set_border_width(14)
        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        title = Gtk.Label(label="재생목록", xalign=0)
        title.get_style_context().add_class("section-title")
        count = Gtk.Label(label=f"{len(self.playlist)}개 영상", xalign=1)
        count.get_style_context().add_class("muted")
        heading.pack_start(title, True, True, 0)
        heading.pack_end(count, False, False, 0)
        panel.pack_start(heading, False, False, 4)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.playlist_box = Gtk.ListBox()
        self.playlist_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.playlist_box.set_activate_on_single_click(True)
        self.playlist_box.connect("row-activated", self.on_playlist_row_activated)
        for index, path in enumerate(self.playlist):
            row = Gtk.ListBoxRow()
            row.get_style_context().add_class("playlist-row")
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            number = Gtk.Label(label=f"{index + 1:02d}")
            number.get_style_context().add_class("track-number")
            name = Gtk.Label(label=os.path.basename(path), xalign=0)
            name.set_ellipsize(3)
            name.set_tooltip_text(path)
            name.get_style_context().add_class("track-title")
            line.pack_start(number, False, False, 0)
            line.pack_start(name, True, True, 0)
            row.add(line)
            self.playlist_box.add(row)
            self.playlist_rows.append(row)
        scroll.add(self.playlist_box)
        panel.pack_start(scroll, True, True, 0)
        return panel

    def on_playlist_toggle(self, _button):
        self.sidebar.set_visible(not self.sidebar.get_visible())

    def on_playlist_row_activated(self, _listbox, row):
        index = row.get_index()
        if index != self.current_index:
            self.current_index = index
            self.play_current_video()

    def refresh_playlist_ui(self):
        if not self.playlist:
            return
        filename = os.path.basename(self.playlist[self.current_index])
        self.now_playing_label.set_text(
            f"재생 중  ·  {filename}   {self.current_index + 1}/{len(self.playlist)}"
        )
        for index, row in enumerate(self.playlist_rows):
            context = row.get_style_context()
            if index == self.current_index:
                context.add_class("playlist-row-active")
            else:
                context.remove_class("playlist-row-active")

    @staticmethod
    def format_time(nanoseconds):
        total_seconds = max(0, int(nanoseconds / Gst.SECOND))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    def update_playback_ui(self):
        if not self.pipeline:
            return True
        position_ok, position = self.pipeline.query_position(Gst.Format.TIME)
        pos_sec = int(position / Gst.SECOND) if position_ok else -1

        # 초(second) 단위가 바뀌었을 때만 GTK UI를 갱신하여 X11 Re-draw 부하 제거
        if position_ok and pos_sec != self.last_ui_pos_sec:
            self.last_ui_pos_sec = pos_sec
            if not self.is_video_only:
                self.position_label.set_text(self.format_time(position))
                if self.duration_ns == 0:
                    duration_ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
                    if duration_ok and duration > 0:
                        self.duration_ns = duration
                        self.duration_label.set_text(self.format_time(duration))
                if self.duration_ns > 0 and not self.is_seeking:
                    self.progress_scale.set_value(min(100, position * 100 / self.duration_ns))

        self.stats_ticks += 1
        if self.video_sink and self.stats_ticks % 10 == 0 and self.video_sink.find_property("stats"):
            stats = self.video_sink.get_property("stats")
            if stats:
                rendered = stats.get_value("rendered") or 0
                dropped = stats.get_value("dropped") or 0
                if dropped > self.last_dropped_frames:
                    print(f"📊 [렌더링 통계] rendered={rendered}, dropped={dropped}")
                self.last_dropped_frames = dropped
        return True

    def on_seek_start(self, _scale, _event):
        self.is_seeking = True
        return False

    def on_seek_end(self, scale, _event):
        if self.pipeline and self.duration_ns > 0:
            target = int(self.duration_ns * scale.get_value() / 100)
            self.pipeline.seek_simple(
                Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, target
            )
        self.is_seeking = False
        return False

    def on_volume_changed(self, scale):
        if self.pipeline:
            self.pipeline.set_property("volume", scale.get_value() / 100.0)

    def hide_cursor(self):
        """마우스 커서를 투명(숨김) 커서로 설정합니다."""
        self.cursor_hide_timer_id = None
        gdk_win = self.get_window()
        if gdk_win:
            display = gdk_win.get_display()
            blank_cursor = None
            try:
                blank_cursor = Gdk.Cursor.new_from_name(display, "none")
            except Exception:
                pass
            if not blank_cursor:
                blank_cursor = Gdk.Cursor.new_for_display(display, Gdk.CursorType.BLANK_CURSOR)
            gdk_win.set_cursor(blank_cursor)
            self.is_cursor_hidden = True
        return False

    def show_cursor(self):
        """마우스 커서를 기본 포인터로 복원합니다."""
        if getattr(self, "cursor_hide_timer_id", None):
            try:
                GLib.source_remove(self.cursor_hide_timer_id)
            except Exception:
                pass
            self.cursor_hide_timer_id = None
        gdk_win = self.get_window()
        if gdk_win:
            gdk_win.set_cursor(None)
        self.is_cursor_hidden = False

    def on_mouse_motion(self, widget, event):
        """마우스 움직임 감지 시 커서를 표시하고 2.5초 후 자동 숨김 타이머를 재설정합니다."""
        if self.is_video_only:
            if self.is_cursor_hidden:
                self.show_cursor()
            if getattr(self, "cursor_hide_timer_id", None):
                try:
                    GLib.source_remove(self.cursor_hide_timer_id)
                except Exception:
                    pass
            self.cursor_hide_timer_id = GLib.timeout_add(2500, self.hide_cursor)
        return False

    def on_window_button_press(self, widget, event):
        """더블클릭 시 전체화면 전환 및 마우스 조작 감지"""
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.toggle_fullscreen()
            return True
        if self.is_video_only:
            self.on_mouse_motion(widget, event)
        return False

    def toggle_fullscreen(self):
        """상단바, 재생목록, 컨트롤을 숨긴 영상 전용 전체화면을 전환합니다."""
        if not self.is_video_only:
            self.sidebar_was_visible = self.sidebar.get_visible()
            self.topbar.hide()
            self.sidebar.hide()
            self.controls.hide()
            self.fullscreen()
            self.set_keep_above(True)
            self.is_fullscreen = True
            self.is_video_only = True
            self.fullscreen_button.set_label("⧉")
            # 전체화면 전환 시 마우스 커서 즉시 숨김
            self.hide_cursor()
            print("🖥️ 영상 전용 전체화면 (마우스 커서 자동 숨김)")
        else:
            self.topbar.show()
            self.controls.show()
            if self.sidebar_was_visible:
                self.sidebar.show()
            self.is_video_only = False
            self.fullscreen_button.set_label("⛶")
            # 일반 모드 복귀 시 마우스 커서 복원
            self.show_cursor()
            print("🖥️ 플레이어 UI 표시")

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
            if element.find_property("num-extra-surfaces"):
                element.set_property("num-extra-surfaces", 32)
            if element.find_property("enable-max-performance"):
                element.set_property("enable-max-performance", True)
            if element.find_property("drop-frame-interval"):
                element.set_property("drop-frame-interval", 0)
        if "nvvidconv" in fname or "nvvidconv" in ename:
            if element.find_property("output-buffers"):
                element.set_property("output-buffers", 32)
            if element.find_property("interpolation-method"):
                # 최고 품질 보간 알고리즘 (5: Nicest 10-tap) 적용하여 픽셀 선명도 극대화
                element.set_property("interpolation-method", 5)
        if "nveglglessink" in fname or "nveglglessink" in ename:
            if element.find_property("force-aspect-ratio"):
                element.set_property("force-aspect-ratio", True)

        # 자막 렌더링 요소 최적화 (외곽선, Noto Sans 폰트, 하단 정렬, 비디오 멈춤 방지)
        if any(k in fname or k in ename for k in ["textoverlay", "subtitleoverlay", "textrender"]):
            if element.find_property("font-desc"):
                element.set_property("font-desc", "Noto Sans, NanumGothic, Sans Bold 24")
            if element.find_property("valignment"):
                element.set_property("valignment", 1)  # bottom
            if element.find_property("halignment"):
                element.set_property("halignment", 1)  # center
            if element.find_property("wait-text"):
                # 자막 패킷 대기로 인한 비디오 지연/멈춤 방지
                element.set_property("wait-text", False)
            if element.find_property("shaded-background"):
                element.set_property("shaded-background", False)
            if element.find_property("outline-color"):
                element.set_property("outline-color", 0xFF000000)
            if element.find_property("color"):
                element.set_property("color", 0xFFFFFFFF)
            if element.find_property("auto-resize"):
                element.set_property("auto-resize", True)
        if "subparse" in fname or "subparse" in ename:
            if element.find_property("subtitle-encoding"):
                element.set_property("subtitle-encoding", "UTF-8")

    def check_video_hw_support(self, file_path):
        """
        ffprobe JSON 정보를 분석하여 Jetson NVDEC 하드웨어 디코더가
        100% 안정적으로 가속 지원하는 포맷(H.265/HEVC 및 H.264 8-bit)인지 판정합니다.
        JetPack 드라이버 상 DPB/버퍼 결함이 발생하는 AV1, VP9 등의 코덱이나
        H.264 10-bit 영상은 미지원으로 분류하여 H.265로 자동 변환하도록 유도합니다.
        """
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt,profile,width,height,color_space,color_transfer,color_primaries",
                "-of", "json",
                file_path
            ]
            data = json.loads(subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True))
            if not data.get("streams"):
                return False, "비디오 스트림 없음"
            stream = data["streams"][0]
            codec = stream.get("codec_name", "").lower()
            pix_fmt = stream.get("pix_fmt", "").lower()
            profile = stream.get("profile", "").lower()

            # 1. H.265 / HEVC -> 8-bit 및 10-bit 모두 Jetson NVDEC 하드웨어 가속 100% 완벽 지원
            if codec in ["hevc", "h265"]:
                bit_depth = "10-bit" if "10" in pix_fmt or "p10" in pix_fmt else "8-bit"
                return True, f"HEVC ({codec.upper()}) {bit_depth} NVDEC 지원"

            # 2. H.264 / AVC -> 8-bit만 지원 (High 10 / yuv420p10le 등 10-bit는 NVDEC 미지원)
            if codec in ["h264", "avc"]:
                if "10" in pix_fmt or "10" in profile or "p10" in pix_fmt:
                    return False, f"H.264 10-bit NVDEC 미지원 ({pix_fmt}/{profile})"
                return True, "H.264 8-bit NVDEC 지원"

            # 3. 그 외 (AV1, VP9, VP8 등) -> JetPack nvv4l2decoder DPB 결함 및 SW 디코딩 병목 방지를 위해 H.265 변환 대상
            return False, f"NVDEC 미지원/불안정 코덱 ({codec.upper()})"
        except Exception as e:
            return False, f"코덱 분석 실패 ({e})"

    def probe_video(self, file_path):
        """변환 품질 결정을 위해 이름 순서에 의존하지 않는 ffprobe 정보를 반환합니다."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,profile,color_space,color_transfer,color_primaries",
            "-of", "json", file_path,
        ]
        data = json.loads(subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True))
        if not data.get("streams"):
            raise ValueError("비디오 스트림이 없습니다")
        return data["streams"][0]

    def auto_convert_to_h265(self, file_path):
        """
        하드웨어 디코딩 미지원 영상을 H.265 (HEVC) MP4 포맷으로 자동 변환하고,
        원래 영상 파일은 'unsupported_originals' 백업 폴더로 안전하게 이동합니다.
        """
        dir_name = os.path.dirname(file_path)
        base_name = os.path.basename(file_path)
        name_no_ext, _ext = os.path.splitext(base_name)

        # 1. 백업 폴더 생성 (unsupported_originals)
        backup_dir = os.path.join(dir_name, "unsupported_originals")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, base_name)

        # 2. H.265 변환 목표 파일 경로 생성 (.mp4)
        target_mp4_path = os.path.join(dir_name, f"{name_no_ext}_h265.mp4")
        if os.path.exists(target_mp4_path):
            supported, _reason = self.check_video_hw_support(target_mp4_path)
            if supported:
                print(f"ℹ️ 기존 H.265 변환본을 사용합니다: {target_mp4_path}")
                return target_mp4_path

        # 3. 비트 심도 검사 (10-bit 소스는 H.265 10-bit 유지)
        _is_supported, reason = self.check_video_hw_support(file_path)
        try:
            stream = self.probe_video(file_path)
        except Exception as error:
            print(f"❌ 변환용 영상 정보 확인 실패: {error}")
            return file_path
        source_pix_fmt = stream.get("pix_fmt", "").lower()
        is_10bit = "10" in source_pix_fmt or "p10" in source_pix_fmt
        pix_fmt = "yuv420p10le" if is_10bit else "yuv420p"
        profile = "main10" if is_10bit else "main"
        temp_output = os.path.join(dir_name, f".{name_no_ext}_h265.part.mp4")

        print(f"\n🔄 [자동 코덱 변환 개시] {base_name}")
        print(f"   - 감지된 사유: {reason}")
        print(f"   - 타겟 코덱: H.265 / HEVC MP4 ({pix_fmt})")
        print(f"   - 백업 이동 경로: {backup_path}")

        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?",
            "-map_metadata", "0", "-map_chapters", "0",
            "-pix_fmt", pix_fmt,
            "-c:v", "libx265",
            "-profile:v", profile,
            "-preset", "fast",
            "-crf", "18",
            "-threads", "6",
            "-c:a", "aac",
            "-b:a", "256k",
            "-c:s", "mov_text",
            "-movflags", "+faststart",
            "-tag:v", "hvc1",
            temp_output
        ]

        try:
            subprocess.run(ffmpeg_cmd, check=True)
            os.replace(temp_output, target_mp4_path)
            print(f"✅ [H.265 변환 완료] {os.path.basename(target_mp4_path)}")

            if os.path.exists(file_path) and file_path != target_mp4_path:
                if os.path.exists(backup_path):
                    base, suffix = os.path.splitext(base_name)
                    counter = 1
                    while os.path.exists(backup_path):
                        backup_path = os.path.join(backup_dir, f"{base}_{counter}{suffix}")
                        counter += 1
                shutil.move(file_path, backup_path)
                print(f"📦 [원본 파일 백업 이동 완료] {backup_path}")

            return target_mp4_path
        except Exception as e:
            print(f"❌ [변환 실패] {file_path}: {e}")
            if os.path.exists(temp_output):
                os.unlink(temp_output)
            return file_path

    def build_playlist(self):
        """입력값을 분석하여 재생 목록을 동적으로 구성하고, 하드웨어 미지원 코덱은 H.265로 자동 변환 및 백업합니다."""
        abs_path = os.path.abspath(self.input_path)
        
        raw_playlist = []
        if os.path.isdir(abs_path):
            self.is_single_file_mode = False
            video_exts = {'.webm', '.mp4', '.mkv', '.mov', '.avi', '.ts', '.m4v'}
            try:
                for fname in os.listdir(abs_path):
                    _stem, ext = os.path.splitext(fname)
                    if ext.lower() in video_exts:
                        full_p = os.path.join(abs_path, fname)
                        if os.path.isfile(full_p):
                            raw_playlist.append(full_p)
            except Exception as e:
                print(f"❌ 디렉토리 읽기 실패 ({abs_path}): {e}")
                sys.exit(1)
            raw_playlist.sort()
            
            if not raw_playlist:
                print(f"❌ 에러: [{self.input_path}] 폴더 내에 재생 가능한 영상 파일이 없습니다.")
                sys.exit(1)

        elif os.path.isfile(abs_path):
            self.is_single_file_mode = True
            raw_playlist.append(abs_path)
        else:
            print(f"❌ 에러: [{self.input_path}] 존재하지 않는 파일이거나 올바르지 않은 경로입니다.")
            sys.exit(1)

        # 중복 제거 및 하드웨어 미지원 영상 자동 H.265 변환 / 백업 검사
        processed_set = set()
        for path in raw_playlist:
            if not os.path.exists(path) or path in processed_set:
                continue

            is_supported, _reason = self.check_video_hw_support(path)
            if not is_supported:
                # 하드웨어 미지원 코덱 발견시 H.265 변환 및 원본 백업 수행
                final_path = self.auto_convert_to_h265(path)
            else:
                final_path = path

            if final_path not in self.playlist:
                self.playlist.append(final_path)
                processed_set.add(final_path)

        mode_str = "단일 파일 반복 모드" if self.is_single_file_mode else "폴더 순환 모드"
        print(f"📂 [{mode_str}] 총 {len(self.playlist)}개의 NVDEC 가속 영상을 재생합니다.")
        for idx, path in enumerate(self.playlist):
            print(f"   [{idx}] {os.path.basename(path)}")

    def on_realize(self, widget):
        """GTK 창의 리소스가 로드되었을 때 영상 재생을 시작합니다."""
        if self.pipeline is not None:
            return
        print("🖥️ GUI 창 준비 완료. 영상 재생을 시작합니다.")
        
        top_window = self.get_window()
        if top_window:
            enable_x11_compositor_bypass(top_window)

        self.play_current_video()

    def play_current_video(self):
        """[성능 최적화] 영상 전환 시 기존 파이프라인을 완전히 해제하고 신규 구축하여 EGL surface 및 하드웨어 디코더 락을 방지합니다."""
        video_path = self.playlist[self.current_index]
        print(f"\n▶ [{self.current_index + 1}/{len(self.playlist)}] 재생 중: {os.path.basename(video_path)}")
        self.refresh_playlist_ui()
        self.duration_ns = 0
        self.progress_scale.set_value(0)
        self.position_label.set_text("00:00")
        self.duration_label.set_text("00:00")
        self.decoder_names.clear()
        self.last_dropped_frames = 0
        self.last_ui_pos_sec = -1

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
        self.pipeline = Gst.ElementFactory.make("playbin", "player")

        # 젯슨 HW 디코더 동적 속성 설정을 위한 deep-element-added 시그널 연결
        self.pipeline.connect("deep-element-added", self.on_deep_element_added)

        # 자막 파일 전체 탐색 및 파싱
        all_sub_files = find_all_matching_subtitles(video_path)
        self.available_subtitles = []
        for idx, s_path in enumerate(all_sub_files):
            evs = parse_subtitle_file_events(s_path)
            if evs:
                color = SUBTITLE_COLORS[idx % len(SUBTITLE_COLORS)]
                lbl = get_subtitle_label(s_path)
                self.available_subtitles.append({
                    'path': s_path,
                    'label': lbl,
                    'color': color,
                    'events': evs
                })

        # 기본 선택: 첫 번째 자막 활성화
        self.active_subtitle_indices = set()
        if self.available_subtitles:
            self.active_subtitle_indices.add(0)
            self.has_subtitles = True
            print(f"💬 [자막 발견 ({len(self.available_subtitles)}개)] " + ", ".join([s['label'] for s in self.available_subtitles]))
        else:
            self.has_subtitles = False

        # 0x01 (video) + 0x02 (audio) + 0x04 (text/subtitles) + 0x10 (soft-volume) = 0x00000017
        self.pipeline.set_property("flags", 0x00000017)

        # Totem 공식 네이티브 GTK OpenGL 비디오 싱크 할당 (60Hz V-Sync 완벽 일치 & 4K 1:1 선명도 보장)
        if self.video_sink:
            if self.video_sink.find_property("sync"):
                self.video_sink.set_property("sync", True)
            if self.video_sink.find_property("qos"):
                self.video_sink.set_property("qos", False)
            if self.video_sink.find_property("max-lateness"):
                self.video_sink.set_property("max-lateness", -1)
            self.pipeline.set_property("video-sink", self.video_sink)

        # autoaudiosink가 실제 사용 가능한 PulseAudio/ALSA 장치를 선택하게 합니다.
        for sink_name in ["autoaudiosink", "fakesink"]:
            asink = Gst.ElementFactory.make(sink_name, "asink")
            if asink:
                if sink_name != "fakesink":
                    if asink.find_property("sync"):
                        asink.set_property("sync", True)
                self.pipeline.set_property("audio-sink", asink)
                break

        # 버스 이벤트 연결
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.enable_sync_message_emission()
        self.bus.connect("sync-message::element", self.on_sync_message)
        self.bus.connect("message", self.on_bus_message)

        # URI 속성 갱신 후 플레이 시작
        self.pipeline.set_property("uri", video_uri)
        self.pipeline.set_property("volume", self.volume_scale.get_value() / 100.0)

        # 선택된 자막 파일 병합 및 즉시 적용
        self.reload_and_apply_subtitles()

        self.pipeline.set_state(Gst.State.PLAYING)
        self.is_playing = True
        self.play_button.set_label("Ⅱ")
        
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
        if message.type == Gst.MessageType.EOS:
            self.retry_counts.pop(self.playlist[self.current_index], None)
            if self.is_single_file_mode:
                print("🔄 단일 영상 완료: 파이프라인 자원 세척 후 재선언 재생합니다.")
                # 장시간 재생 시 EGL surface/시계동기화 락 방지를 위해 파이프라인 완전 재구축 수행
                GLib.timeout_add(10, self.play_current_video)
            else:
                self.play_next_video()
            
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"❌ 재생 중 에러 발생: {err}")
            if debug:
                print(f"   GStreamer: {debug}")
            path = self.playlist[self.current_index]
            retries = self.retry_counts.get(path, 0)
            if retries < self.max_retries:
                self.retry_counts[path] = retries + 1
                print(f"🔄 재생 파이프라인 재시도 ({retries + 1}/{self.max_retries})")
                GLib.timeout_add(250, self.play_current_video)
            elif self.is_single_file_mode:
                print("⏹ 반복 오류로 재생을 중단합니다. 원본과 디코더 로그를 확인하세요.")
                self.pipeline.set_state(Gst.State.PAUSED)
            else:
                print("⏭ 반복 오류 항목을 건너뜁니다.")
                self.play_next_video()

        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self.pipeline:
            _old_state, new_state, _pending = message.parse_state_changed()
            self.is_playing = new_state == Gst.State.PLAYING
            self.play_button.set_label("Ⅱ" if self.is_playing else "▶")

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

        res = self.pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            target_ns
        )
        if not res:
            print("⚠️ 탐색 실패로 파이프라인을 재구축합니다.")
            self.play_current_video()
            return

        direction = "앞으로" if offset_seconds > 0 else "뒤로"
        print(f"⏩ {direction} {abs(offset_seconds)}초 이동 (현재 위치: {target_ns / Gst.SECOND:.1f}초)")

    def toggle_play_pause(self):
        """일시 정지 / 재생 상태를 전환합니다."""
        if not self.pipeline:
            return
            
        if self.is_playing:
            self.pipeline.set_state(Gst.State.PAUSED)
            self.is_playing = False
            self.play_button.set_label("▶")
            print("⏸ 일시 정지")
        else:
            self.pipeline.set_state(Gst.State.PLAYING)
            self.is_playing = True
            self.play_button.set_label("Ⅱ")
            print("▶ 다시 재생")

    def play_next_video(self):
        """다음 영상으로 전환합니다."""
        if self.is_single_file_mode:
            GLib.timeout_add(10, self.play_current_video)
        else:
            self.current_index = (self.current_index + 1) % len(self.playlist)
            print("⏭ 다음 영상으로 넘어갑니다.")
            GLib.timeout_add(50, self.play_current_video)

    def play_prev_video(self):
        """이전 영상으로 전환합니다."""
        if self.is_single_file_mode:
            GLib.timeout_add(10, self.play_current_video)
        else:
            self.current_index = (self.current_index - 1 + len(self.playlist)) % len(self.playlist)
            print("⏮ 이전 영상으로 넘어갑니다.")
            GLib.timeout_add(50, self.play_current_video)

    def build_subtitle_popover(self):
        """다중 자막 선택 팝오버(Popover) 창을 구성합니다."""
        self.sub_popover = Gtk.Popover(relative_to=self.sub_button)
        self.sub_popover.set_position(Gtk.PositionType.TOP)
        self.sub_popover.set_border_width(12)
        
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # 헤더
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="💬 자막 선택 (다중 동시 표시 지원)", xalign=0)
        title.get_style_context().add_class("popover-title")
        header.pack_start(title, True, True, 0)
        container.pack_start(header, False, False, 2)
        
        hint = Gtk.Label(label="여러 개를 체크하면 화면에 동시에 색상별로 표시됩니다.", xalign=0)
        hint.get_style_context().add_class("muted")
        container.pack_start(hint, False, False, 0)
        
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        container.pack_start(sep, False, False, 2)

        # 자막 체크박스 리스트
        self.sub_checkboxes = []
        for idx, sub in enumerate(self.available_subtitles):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            
            # 색상 표시 원형 인디케이터
            color_box = Gtk.DrawingArea()
            color_box.set_size_request(12, 12)
            c_hex = sub['color']
            def draw_color_dot(widget, cr, col_hex):
                try:
                    r = int(col_hex[1:3], 16) / 255.0
                    g = int(col_hex[3:5], 16) / 255.0
                    b = int(col_hex[5:7], 16) / 255.0
                    cr.set_source_rgb(r, g, b)
                    cr.arc(6, 6, 5, 0, 2 * 3.14159)
                    cr.fill()
                except Exception:
                    pass
            color_box.connect("draw", draw_color_dot, c_hex)
            row.pack_start(color_box, False, False, 2)
            
            chk = Gtk.CheckButton(label=sub['label'])
            chk.set_active(idx in self.active_subtitle_indices)
            chk.connect("toggled", self.on_subtitle_checkbox_toggled, idx)
            row.pack_start(chk, True, True, 0)
            
            self.sub_checkboxes.append(chk)
            container.pack_start(row, False, False, 2)
            
        # 전체 선택 / 전체 해제 버튼
        btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_bar.get_style_context().add_class("sub-btn-row")
        select_all_btn = Gtk.Button(label="모두 선택")
        select_all_btn.connect("clicked", self.on_select_all_subtitles)
        deselect_all_btn = Gtk.Button(label="모두 해제")
        deselect_all_btn.connect("clicked", self.on_deselect_all_subtitles)
        btn_bar.pack_start(select_all_btn, True, True, 0)
        btn_bar.pack_start(deselect_all_btn, True, True, 0)
        container.pack_start(btn_bar, False, False, 4)
        
        container.show_all()
        self.sub_popover.add(container)

    def show_subtitle_popover(self):
        """자막 선택 팝오버를 열거나 닫습니다."""
        if not self.available_subtitles:
            print("ℹ️ 현재 영상에 사용 가능한 자막이 없습니다.")
            return
        if self.sub_popover:
            self.sub_popover.destroy()
            self.sub_popover = None
        self.build_subtitle_popover()
        self.sub_popover.show_all()
        self.sub_popover.popup()

    def on_sub_button_clicked(self, widget):
        """자막 버튼 클릭 시 단일 자막은 토글, 다중 자막은 팝오버 메뉴를 표시합니다."""
        if not self.available_subtitles:
            return
        if len(self.available_subtitles) == 1:
            self.toggle_subtitles()
        else:
            self.show_subtitle_popover()

    def on_subtitle_checkbox_toggled(self, chk_button, track_idx):
        """자막 체크박스 토글 시 실시간으로 활성 자막 목록을 갱신하고 화면에 즉시 반영합니다."""
        if chk_button.get_active():
            self.active_subtitle_indices.add(track_idx)
            self.subtitles_enabled = True
        else:
            self.active_subtitle_indices.discard(track_idx)
            if not self.active_subtitle_indices:
                self.subtitles_enabled = False
        self.reload_and_apply_subtitles()

    def on_select_all_subtitles(self, _btn):
        """모든 자막 체크 활성화"""
        for chk in getattr(self, "sub_checkboxes", []):
            chk.set_active(True)

    def on_deselect_all_subtitles(self, _btn):
        """모든 자막 체크 해제"""
        for chk in getattr(self, "sub_checkboxes", []):
            chk.set_active(False)

    def reload_and_apply_subtitles(self):
        """선택된 다중 자막 트랙들을 실시간 병합하여 GStreamer 파이프라인에 즉시 반영합니다."""
        if not self.pipeline:
            return
            
        video_path = self.playlist[self.current_index]
        active_tracks = []
        for idx in sorted(list(self.active_subtitle_indices)):
            if 0 <= idx < len(self.available_subtitles):
                sub = self.available_subtitles[idx]
                active_tracks.append((sub['label'], sub['color'], sub['events']))
                
        if active_tracks and self.subtitles_enabled:
            merged_file = generate_merged_subtitle_file(active_tracks, video_path)
            if merged_file:
                sub_uri = f"file://{pathname2url(os.path.abspath(merged_file))}"
                self.pipeline.set_property("suburi", sub_uri)
                self.pipeline.set_property("current-text", 0)
                selected_labels = [t[0] for t in active_tracks]
                print(f"💬 [다중 자막 렌더링 ({len(active_tracks)}개)] " + ", ".join(selected_labels))
            else:
                self.pipeline.set_property("current-text", -1)
        else:
            self.pipeline.set_property("current-text", -1)
            print("💬 [자막] 표시 꺼짐 (OFF)")
            
        self.update_subtitle_button_ui()

    def update_subtitle_button_ui(self):
        """자막 버튼 레이블 및 활성화 상태 갱신"""
        if not hasattr(self, "sub_button"):
            return
        total = len(self.available_subtitles)
        if total == 0:
            self.sub_button.set_label("💬 자막 없음")
            self.sub_button.set_sensitive(False)
            self.sub_button.set_tooltip_text("자막 없음")
        elif total == 1:
            if self.subtitles_enabled and self.active_subtitle_indices:
                self.sub_button.set_label("💬 자막 ON")
            else:
                self.sub_button.set_label("💬 자막 OFF")
            self.sub_button.set_sensitive(True)
            self.sub_button.set_tooltip_text("자막 켜기/끄기 (S)")
        else:
            active_cnt = len(self.active_subtitle_indices) if self.subtitles_enabled else 0
            self.sub_button.set_label(f"💬 자막 ({active_cnt}/{total})")
            self.sub_button.set_sensitive(True)
            self.sub_button.set_tooltip_text(f"다중 자막 선택 메뉴 (S: 토글, C: 선택 창) - {total}개 사용 가능")

    def toggle_subtitles(self):
        """자막 켜기/끄기 상태를 토글합니다."""
        if not self.available_subtitles:
            print("ℹ️ 현재 영상에 로드된 자막이 없습니다.")
            return

        self.subtitles_enabled = not self.subtitles_enabled
        if self.subtitles_enabled and not self.active_subtitle_indices:
            self.active_subtitle_indices.add(0)
            
        self.reload_and_apply_subtitles()

    def on_key_press(self, widget, event):
        """키보드 입력 이벤트 제어"""
        keyname = Gdk.keyval_name(event.keyval)
        
        if keyname == "Escape" and self.is_video_only:
            self.toggle_fullscreen()
            return True
        elif keyname in ["Escape", "q", "Q"]:
            print("⏹ 프로그램 종료.")
            self.on_destroy(widget)
            return True
        elif keyname == "space":
            self.toggle_play_pause()
            return True
        elif keyname == "Right":
            self.seek_relative(10)
            return True
        elif keyname == "Left":
            self.seek_relative(-10)
            return True
        elif keyname in ["n", "N"]:
            self.play_next_video()
            return True
        elif keyname in ["p", "P"]:
            self.play_prev_video()
            return True
        elif keyname in ["s", "S"]:
            self.toggle_subtitles()
            return True
        elif keyname in ["c", "C"]:
            self.show_subtitle_popover()
            return True
        elif keyname in ["f", "F"]:
            self.toggle_fullscreen()
            return True
            
        return False

    def on_destroy(self, widget):
        if getattr(self, "cursor_hide_timer_id", None):
            try:
                GLib.source_remove(self.cursor_hide_timer_id)
            except Exception:
                pass
            self.cursor_hide_timer_id = None
        self.show_cursor()

        if getattr(self, "position_timer_id", None):
            try:
                GLib.source_remove(self.position_timer_id)
            except Exception:
                pass
            self.position_timer_id = None
        if self.bus is not None:
            try:
                self.bus.remove_signal_watch()
            except Exception:
                pass
            self.bus = None
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        if Gtk.main_level() > 0:
            Gtk.main_quit()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ 사용법: python3 jetson_player.py [폴더_경로 또는 파일_경로]")
        sys.exit(1)
        
    Gst.init(None)
    Gtk.init(None)
    
    user_input = sys.argv[1]
    win = JetsonSignageFlexiblePlayer(user_input)
    win.show_all()
    Gtk.main()
