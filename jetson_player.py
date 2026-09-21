#!/usr/bin/env python3
import sys
import os
import glob
import subprocess
import shutil
import json
import re
import hashlib
import html
import time
import threading
import gi
from urllib.request import pathname2url

# 환경 변수 자동 설정 (cannot open display 에러 방지)
if "DISPLAY" not in os.environ:
    if os.path.exists("/tmp/.X11-unix/X1"):
        os.environ["DISPLAY"] = ":1"
    else:
        os.environ["DISPLAY"] = ":0"
if "XDG_RUNTIME_DIR" not in os.environ:
    os.environ["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"

# 필요한 GStreamer 및 GTK 컴포넌트 로드
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GdkX11', '3.0')
gi.require_version('Pango', '1.0')
from gi.repository import Gst, Gtk, Gdk, GstVideo, GLib, GdkX11, Pango

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

CACHE_DIR = os.path.expanduser("~/.cache/jetson_video_player")
CACHE_FILE = os.path.join(CACHE_DIR, "hw_cache.json")

class HWSupportCache:
    """비디오 파일별 하드웨어 적합성 ffprobe 분석 결과를 디스크에 영구 캐시하여 시작 지연을 방지합니다."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.is_dirty = False
        self._load()

    def _load(self):
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
        except Exception as e:
            self.cache = {}

    def save(self):
        with self.lock:
            if not self.is_dirty:
                return
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.cache, f, ensure_ascii=False, indent=2)
                self.is_dirty = False
            except Exception:
                pass

    def get(self, file_path):
        try:
            st = os.stat(file_path)
            mtime = st.st_mtime
            size = st.st_size
        except Exception:
            return None

        with self.lock:
            entry = self.cache.get(file_path)
            if entry and entry.get("mtime") == mtime and entry.get("size") == size:
                return entry.get("supported", False), entry.get("reason", "")
        return None

    def set(self, file_path, supported, reason):
        try:
            st = os.stat(file_path)
            mtime = st.st_mtime
            size = st.st_size
        except Exception:
            mtime = 0
            size = 0

        with self.lock:
            self.cache[file_path] = {
                "mtime": mtime,
                "size": size,
                "supported": supported,
                "reason": reason
            }
            self.is_dirty = True

hw_cache = HWSupportCache()

LANGUAGE_COLORS = {
    'ko': '#FFFFFF',  # 🇰🇷 한국어: 화이트 (메인 기본)
    'en': '#FFE066',  # 🇺🇸 영어: 레몬 옐로우 (화사하고 뛰어난 가독성)
    'zh': '#64D2FF',  # 🇨🇳 중국어: 시안/스카이블루 (시원하고 직관적)
    'ja': '#69F0AE',  # 🇯🇵 일본어: 네온 민트 (눈에 편안한 그린)
    'es': '#FF80AB',  # 🇪🇸 스페인어: 소프트 핑크
    'fr': '#FFB74D',  # 🇫🇷 프랑스어: 앰버 오렌지
    'de': '#D1C4E9',  # 🇩🇪 독일어: 소프트 라벤더
    'ru': '#FF8A80',  # 🇷🇺 러시아어: 코랄 레드
}

FALLBACK_PALETTE = ["#B388FF", "#80CBC4", "#FFF59D", "#FFAB91", "#CE93D8", "#80DEEA"]

def get_subtitle_color(file_path, index=0):
    """자막 파일의 언어 태그를 분석하여 언어별 최적 고대비 고유 색상을 반환합니다."""
    stem = os.path.basename(file_path).lower()
    if any(k in stem for k in ['.ko', '.kor', '.kr', '_ko', '_kor', '_kr', '.korean', '한국어', '한글']):
        return LANGUAGE_COLORS['ko']
    elif any(k in stem for k in ['.en', '.eng', '_en', '_eng', '.english', '영어', '영문']):
        return LANGUAGE_COLORS['en']
    elif any(k in stem for k in ['.zh', '.chi', '.zho', '_zh', '_chi', '.chinese', '중국어', '중문', '.cmn', 'zh-tw', 'zh-cn']):
        return LANGUAGE_COLORS['zh']
    elif any(k in stem for k in ['.ja', '.jpn', '.jp', '_ja', '_jpn', '.japanese', '일본어', '일어']):
        return LANGUAGE_COLORS['ja']
    elif any(k in stem for k in ['.es', '.spa', '_es', '_spa', '.spanish', '스페인어']):
        return LANGUAGE_COLORS['es']
    elif any(k in stem for k in ['.fr', '.fre', '.fra', '_fr', '_fre', '.french', '프랑스어']):
        return LANGUAGE_COLORS['fr']
    elif any(k in stem for k in ['.de', '.ger', '.deu', '_de', '_ger', '.german', '독일어']):
        return LANGUAGE_COLORS['de']
    elif any(k in stem for k in ['.ru', '.rus', '_ru', '_rus', '.russian', '러시아어']):
        return LANGUAGE_COLORS['ru']
    
    return FALLBACK_PALETTE[index % len(FALLBACK_PALETTE)]

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

def get_subtitle_short_badge(label):
    """자막 레이블에서 직관적인 언어 뱃지([KR], [TW], [EN], [JP] 등)를 추출합니다."""
    if "한국어" in label:
        return "[KR] "
    elif "영어" in label:
        return "[EN] "
    elif "중국어" in label or "대만" in label or "zh-TW" in label or "zh-tw" in label:
        return "[TW] "
    elif "일본어" in label:
        return "[JP] "
    elif "스페인어" in label:
        return "[ES] "
    elif "프랑스어" in label:
        return "[FR] "
    elif "독일어" in label:
        return "[DE] "
    return ""

def merge_subtitle_tracks(tracks, font_scale=1.0, offset_ms=0):
    """
    여러 자막 트랙 [(label, color, events), ...]의 타임라인을 정밀 분할하고
    언어별 고유 색상(<font color="...">) 및 싱크 오프셋을 적용하여 SAMI(.smi) 포맷 문자열로 병합합니다.
    GStreamer subparse는 SAMI 포맷의 <font color="..."> 태그를 완벽한 Pango markup(<span foreground="...">)으로
    변환하여 화면에 줄별 고유 색상으로 선명하게 렌더링합니다.
    """
    if not tracks:
        return ""
        
    time_points = set()
    offset_tracks = []
    for label, color, events in tracks:
        shifted_events = []
        for start_ms, end_ms, text in events:
            s = max(0, start_ms + offset_ms)
            e = max(s + 50, end_ms + offset_ms)
            shifted_events.append((s, e, text))
            time_points.add(s)
            time_points.add(e)
        offset_tracks.append((label, color, shifted_events))
            
    sorted_times = sorted(list(time_points))
    if len(sorted_times) < 2:
        return ""
        
    smi_blocks = []
    is_multi = len(offset_tracks) > 1
    
    for i in range(len(sorted_times) - 1):
        t_start = sorted_times[i]
        t_end = sorted_times[i + 1]
        if t_end <= t_start:
            continue
            
        active_lines = []
        for label, color, events in offset_tracks:
            for ev_start, ev_end, text in events:
                if ev_start <= t_start and ev_end >= t_end:
                    if text and not text.isspace():
                        badge = get_subtitle_short_badge(label) if is_multi else ""
                        c = color if color else "#FFFFFF"
                        lines = [line.strip() for line in text.splitlines() if line.strip()]
                        if lines:
                            escaped_first = html.escape(f"{badge}{lines[0]}")
                            styled_lines = [f'<font color="{c}">{escaped_first}</font>']
                            for extra_line in lines[1:]:
                                styled_lines.append(f'<font color="{c}">{html.escape(extra_line)}</font>')
                            active_lines.append("<br>".join(styled_lines))
                    break
                    
        if active_lines:
            combined_text = "<br>".join(active_lines)
            smi_blocks.append((t_start, t_end, combined_text))
            
    # 인접 동일 텍스트 블록 병합 및 80ms 미만 극미세 구간 스무딩 최적화
    smoothed = []
    for start, end, text in smi_blocks:
        if not text or text.isspace():
            continue
        if end - start < 80:
            if smoothed and smoothed[-1][2] == text:
                smoothed[-1] = (smoothed[-1][0], end, text)
                continue
            elif end - start < 40:
                continue
        if smoothed and smoothed[-1][1] == start and smoothed[-1][2] == text:
            smoothed[-1] = (smoothed[-1][0], end, text)
        else:
            smoothed.append((start, end, text))
            
    # SAMI 표준 문서 생성
    out = [
        '<SAMI>',
        '<HEAD>',
        '<TITLE>Jetson Multi Subtitles</TITLE>',
        '<STYLE TYPE="text/css"><!-- P { font-family: sans-serif; text-align: center; } .KRCC { Name: Korean; lang: ko-KR; } --></STYLE>',
        '</HEAD>',
        '<BODY>'
    ]
    
    for idx, (start, end, text) in enumerate(smoothed):
        out.append(f'<SYNC Start={start}><P Class=KRCC>{text}</SYNC>')
        next_start = smoothed[idx + 1][0] if idx + 1 < len(smoothed) else end + 1000
        # 다음 대사와의 간격이 200ms 이상일 때만 공백 자막을 삽입하여 subparse 큐 지연 및 싱크 왜곡 방지
        if next_start - end >= 200:
            out.append(f'<SYNC Start={end}><P Class=KRCC>&nbsp;</SYNC>')
            
    out.append('</BODY>')
    out.append('</SAMI>')
    
    return "\n".join(out)

def generate_merged_subtitle_file(active_tracks, video_path, font_scale=1.0, offset_ms=0):
    """
    선택된 자막 트랙들을 언어별 고유 색상이 적용된 SAMI(.smi) 파일로 생성하고 그 경로를 반환합니다.
    """
    if not active_tracks:
        return None
        
    cache_dir = "/tmp/jetson_subtitles"
    os.makedirs(cache_dir, exist_ok=True)
    
    track_ids = "_".join([t[0] for t in active_tracks])
    h = hashlib.md5((video_path + track_ids + f"_{font_scale:.2f}_{offset_ms}").encode('utf-8')).hexdigest()[:14]
    target_file = os.path.join(cache_dir, f"merged_sub_{h}.smi")
    
    smi_content = merge_subtitle_tracks(active_tracks, font_scale=font_scale, offset_ms=offset_ms)
    if not smi_content:
        return None
        
    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(smi_content)
        
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
        self.main_paned = None
        self.sidebar_width = 360
        self.is_adjusting_paned = False
        self.is_wrap_enabled = False
        self.r_text = None
        self.wrap_button = None
        self.is_destroyed = False
        self._bg_checker_started = False
        self.is_seeking = False
        self.duration_ns = 0
        self.tree_store = None
        self.playlist_treeview = None
        self.playlist_tree_iters = {}
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

        # 재생 속도(Playback Speed/Rate) 상태 변수
        self.playback_rate = 1.0
        self.rate_applied_on_preroll = False
        self.speed_button = None
        self.speed_popover = None
        self.fs_speed_button = None

        # 전체화면 플로팅 컨트롤 바 및 OSD 상태 변수
        self.fs_controls_box = None
        self.is_fs_controls_visible = False
        self.is_mouse_over_fs_controls = False
        self.is_popover_open = False
        self.osd_box = None
        self.osd_label = None
        self.osd_timer_id = None
        self.fs_progress_scale = None
        self.fs_position_label = None
        self.fs_duration_label = None
        self.fs_play_button = None
        self.fs_sub_button = None
        self.fs_volume_scale = None

        # 다중 자막(Subtitle) 상태 변수 초기화
        self.subtitles_enabled = True
        self.has_subtitles = False
        self.available_subtitles = []  # list of dicts: {'path', 'label', 'color', 'events'}
        self.active_subtitle_indices = set()  # set of int indices
        self.current_suburi = None
        self.pending_seek_ns = 0
        self.last_known_pos_ns = 0  # 자막 전환 시 0초 튕김 방지용 백업 위치
        self.is_updating_sub_checkboxes = False  # 모두 선택/해제 일괄 변경 락
        self.sub_reload_timer_id = None  # 자막 리로드 디바운스 타이머
        self.subtitle_font_scale = 1.0  # 자막 크기 스케일 (0.6 ~ 1.6)
        self.subtitle_offset_ms = 0  # 자막 싱크 오프셋 (ms 단위, 음수: 빠르게, 양수: 느리게)
        self.scale_label = None
        self.sync_label = None
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

    def show_osd(self, text, timeout_ms=1200):
        """화면 상단 중앙에 설정 변경 상태(속도, 탐색 등)를 알려주는 OSD 박스를 표시합니다."""
        if not getattr(self, "osd_box", None) or not getattr(self, "osd_label", None):
            return
        self.osd_label.set_text(text)
        self.osd_box.show_all()
        if getattr(self, "osd_timer_id", None):
            try:
                GLib.source_remove(self.osd_timer_id)
            except Exception:
                pass
        self.osd_timer_id = GLib.timeout_add(timeout_ms, self._hide_osd)

    def _hide_osd(self):
        if getattr(self, "osd_box", None):
            self.osd_box.hide()
        self.osd_timer_id = None
        return False

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

    def step_playback_rate(self, delta):
        """현재 재생 속도에서 delta만큼 속도를 증감합니다."""
        new_rate = self.playback_rate + delta
        self.set_playback_rate(new_rate)

    def reset_playback_rate(self):
        """재생 속도를 1.0x (기본값)으로 복원합니다."""
        self.set_playback_rate(1.0)

    def update_speed_button_ui(self):
        """재생 속도 버튼 텍스트를 현재 배속에 맞게 갱신합니다."""
        rate_str = f"{self.playback_rate:.2f}x" if (self.playback_rate * 10) % 1 != 0 else f"{self.playback_rate:.1f}x"
        if rate_str.endswith(".0x") and self.playback_rate == 1.0:
            rate_str = "1.0x"
        if getattr(self, "speed_button", None):
            self.speed_button.set_label(f"⚡ {rate_str}")
        if getattr(self, "fs_speed_button", None):
            self.fs_speed_button.set_label(f"⚡ {rate_str}")

    def build_speed_popover(self, parent_btn):
        """재생 속도 선택 팝오버 메뉴를 구성합니다."""
        if getattr(self, "speed_popover", None):
            try:
                self.speed_popover.destroy()
            except Exception:
                pass
            self.speed_popover = None

        self.speed_popover = Gtk.Popover(relative_to=parent_btn)
        self.speed_popover.set_position(Gtk.PositionType.TOP)
        self.speed_popover.set_border_width(12)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        title = Gtk.Label(label="⚡ 재생 속도 조절", xalign=0)
        title.get_style_context().add_class("popover-title")
        container.pack_start(title, False, False, 2)

        # 프리셋 속도 버튼 목록
        presets_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        presets_box.get_style_context().add_class("sub-btn-row")
        for spd in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
            btn = Gtk.Button(label=f"{spd}x")
            if abs(self.playback_rate - spd) < 0.01:
                btn.get_style_context().add_class("primary")
            btn.connect("clicked", lambda _b, s=spd: (self.set_playback_rate(s), self.speed_popover.popdown()))
            presets_box.pack_start(btn, True, True, 0)
        container.pack_start(presets_box, False, False, 2)

        # 미세 조절 바
        step_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        step_box.get_style_context().add_class("sub-btn-row")

        dec_btn = Gtk.Button(label="˗ 느리게 (-0.25x)")
        dec_btn.connect("clicked", lambda _b: self.step_playback_rate(-0.25))
        step_box.pack_start(dec_btn, True, True, 0)

        reset_btn = Gtk.Button(label="1.0x (기본)")
        reset_btn.connect("clicked", lambda _b: (self.reset_playback_rate(), self.speed_popover.popdown()))
        step_box.pack_start(reset_btn, True, True, 0)

        inc_btn = Gtk.Button(label="˖ 빠르게 (+0.25x)")
        inc_btn.connect("clicked", lambda _b: self.step_playback_rate(0.25))
        step_box.pack_start(inc_btn, True, True, 0)

        container.pack_start(step_box, False, False, 2)

        hint = Gtk.Label(label="단축키: Up/Down 또는 d/a (속도 조절), r (1.0x 복원)", xalign=0)
        hint.get_style_context().add_class("muted")
        container.pack_start(hint, False, False, 2)

        container.show_all()
        self.speed_popover.add(container)

        def on_pop_closed(_pop):
            self.is_popover_open = False
        self.speed_popover.connect("closed", on_pop_closed)

    def on_speed_button_clicked(self, widget):
        self.build_speed_popover(widget)
        self.is_popover_open = True
        self.speed_popover.popup()

    def build_fs_controls(self):
        """전체화면(Fullscreen) 모드 전용 플로팅 컨트롤 바 위젯을 생성합니다."""
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        panel.get_style_context().add_class("fs-controls")

        # 타임라인
        timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.fs_position_label = Gtk.Label(label="00:00")
        self.fs_position_label.get_style_context().add_class("muted")

        self.fs_progress_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.fs_progress_scale.set_draw_value(False)
        self.fs_progress_scale.set_hexpand(True)
        self.fs_progress_scale.connect("button-press-event", self.on_seek_start)
        self.fs_progress_scale.connect("button-release-event", self.on_fs_seek_end)

        self.fs_duration_label = Gtk.Label(label="00:00")
        self.fs_duration_label.get_style_context().add_class("muted")

        timeline.pack_start(self.fs_position_label, False, False, 0)
        timeline.pack_start(self.fs_progress_scale, True, True, 0)
        timeline.pack_start(self.fs_duration_label, False, False, 0)
        panel.pack_start(timeline, False, False, 0)

        # 액션 버튼 열
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        prev_btn = Gtk.Button(label="⏮")
        prev_btn.set_tooltip_text("이전 영상 (P)")
        prev_btn.connect("clicked", lambda _b: self.play_prev_video())

        rewind_btn = Gtk.Button(label="↶ 10")
        rewind_btn.set_tooltip_text("10초 뒤로 (←)")
        rewind_btn.connect("clicked", lambda _b: self.seek_relative(-10))

        self.fs_play_button = Gtk.Button(label="Ⅱ")
        self.fs_play_button.get_style_context().add_class("primary")
        self.fs_play_button.set_tooltip_text("재생/일시정지 (Space)")
        self.fs_play_button.connect("clicked", lambda _b: self.toggle_play_pause())

        forward_btn = Gtk.Button(label="10 ↷")
        forward_btn.set_tooltip_text("10초 앞으로 (→)")
        forward_btn.connect("clicked", lambda _b: self.seek_relative(10))

        next_btn = Gtk.Button(label="⏭")
        next_btn.set_tooltip_text("다음 영상 (N)")
        next_btn.connect("clicked", lambda _b: self.play_next_video())

        for b in (prev_btn, rewind_btn, self.fs_play_button, forward_btn, next_btn):
            actions.pack_start(b, False, False, 0)

        # 속도 조절
        fs_speed_down = Gtk.Button(label="˗")
        fs_speed_down.set_tooltip_text("재생 속도 감소 (단축키: Down 또는 a)")
        fs_speed_down.connect("clicked", lambda _b: self.step_playback_rate(-0.25))

        self.fs_speed_button = Gtk.Button(label="1.0x")
        self.fs_speed_button.get_style_context().add_class("speed-btn")
        self.fs_speed_button.set_tooltip_text("재생 속도 조절 (단축키: Up/Down 또는 d/a, r: 1.0x)")
        self.fs_speed_button.connect("clicked", self.on_speed_button_clicked)

        fs_speed_up = Gtk.Button(label="˖")
        fs_speed_up.set_tooltip_text("재생 속도 증가 (단축키: Up 또는 d)")
        fs_speed_up.connect("clicked", lambda _b: self.step_playback_rate(0.25))

        actions.pack_start(fs_speed_down, False, False, 0)
        actions.pack_start(self.fs_speed_button, False, False, 0)
        actions.pack_start(fs_speed_up, False, False, 0)

        spacer = Gtk.Box()
        actions.pack_start(spacer, True, True, 0)

        # 볼륨
        vol_ico = Gtk.Label(label="◖)))")
        vol_ico.get_style_context().add_class("muted")
        actions.pack_start(vol_ico, False, False, 4)

        self.fs_volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.fs_volume_scale.set_size_request(90, -1)
        self.fs_volume_scale.set_draw_value(False)
        self.fs_volume_scale.set_value(100)
        self.fs_volume_scale.connect("value-changed", self.on_fs_volume_changed)
        actions.pack_start(self.fs_volume_scale, False, False, 0)

        # 자막
        self.fs_sub_button = Gtk.Button(label="💬 자막")
        self.fs_sub_button.set_tooltip_text("자막 켜기/끄기 (S)")
        self.fs_sub_button.connect("clicked", self.on_sub_button_clicked)
        actions.pack_end(self.fs_sub_button, False, False, 4)

        # 창 모드로 복귀
        fs_toggle_btn = Gtk.Button(label="⧉")
        fs_toggle_btn.set_tooltip_text("창 모드로 복귀 (F / Esc)")
        fs_toggle_btn.connect("clicked", lambda _b: self.toggle_fullscreen())
        actions.pack_end(fs_toggle_btn, False, False, 0)

        panel.pack_start(actions, False, False, 0)

        panel.connect("enter-notify-event", self._on_fs_controls_enter)
        panel.connect("leave-notify-event", self._on_fs_controls_leave)

        return panel

    def _on_fs_controls_enter(self, widget, event):
        self.is_mouse_over_fs_controls = True
        if getattr(self, "cursor_hide_timer_id", None):
            try:
                GLib.source_remove(self.cursor_hide_timer_id)
            except Exception:
                pass
            self.cursor_hide_timer_id = None
        return False

    def _on_fs_controls_leave(self, widget, event):
        self.is_mouse_over_fs_controls = False
        if self.is_video_only:
            if getattr(self, "cursor_hide_timer_id", None):
                try:
                    GLib.source_remove(self.cursor_hide_timer_id)
                except Exception:
                    pass
            self.cursor_hide_timer_id = GLib.timeout_add(2500, self._on_hide_timer_tick)
        return False

    def on_fs_seek_end(self, scale, _event):
        if self.pipeline and self.duration_ns > 0:
            target = int(self.duration_ns * scale.get_value() / 100)
            self.last_known_pos_ns = target
            self.pipeline.seek(
                self.playback_rate,
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                Gst.SeekType.SET,
                target,
                Gst.SeekType.NONE,
                -1
            )
            self.show_osd(f"⏱️ {self.format_time(target)} / {self.format_time(self.duration_ns)}")
        self.is_seeking = False
        return False

    def on_fs_volume_changed(self, scale):
        val = scale.get_value()
        if hasattr(self, "volume_scale") and abs(self.volume_scale.get_value() - val) > 0.5:
            self.volume_scale.set_value(val)
        if self.pipeline:
            self.pipeline.set_property("volume", val / 100.0)

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
        .fs-controls { background: rgba(17, 21, 29, 0.92); border: 1px solid #303744; border-radius: 12px; padding: 8px 14px; margin: 12px; }
        .osd-box { background: rgba(14, 17, 23, 0.88); border: 1px solid #3b4455; border-radius: 9px; padding: 10px 24px; margin-top: 25px; }
        .osd-text { font-size: 19px; font-weight: 800; color: #e9ff5b; }
        .speed-btn { font-weight: 700; color: #e9ff5b; min-width: 48px; }
        .speed-btn:hover { background: #252b36; }
        treeview {
            background-color: #0e1117;
            color: #dce2ec;
            border: none;
            font-size: 13px;
        }
        treeview:selected {
            background-color: #242b35;
            color: #ffffff;
        }
        treeview:hover {
            background-color: #161b24;
        }
        treeview.view {
            background-color: #0e1117;
            color: #dce2ec;
        }
        treeview.view:selected {
            background-color: #242b35;
            color: #ffffff;
        }
        .tree-tool-btn {
            background: #1a202c;
            border-radius: 5px;
            padding: 3px 8px;
            font-size: 11px;
            color: #a0aec0;
        }
        .tree-tool-btn:hover {
            background: #2d3748;
            color: #ffffff;
        }
        .tree-tool-btn.active {
            background: #e9ff5b;
            color: #111318;
            font-weight: bold;
        }
        .tree-tool-btn.active:hover {
            background: #f2ff91;
            color: #111318;
        }
        paned > separator {
            background-color: #252b36;
            min-width: 5px;
            margin: 0;
        }
        paned > separator:hover {
            background-color: #e9ff5b;
        }
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

        self.main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)

        # 비디오 위젯 및 오버레이(OSD, 전체화면 플로팅 컨트롤) 컨테이너
        self.video_container = Gtk.Overlay()
        self.video_container.add(self.video_widget)

        # 1) OSD 라벨 오버레이 (화면 상단 중앙)
        self.osd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.osd_box.get_style_context().add_class("osd-box")
        self.osd_box.set_halign(Gtk.Align.CENTER)
        self.osd_box.set_valign(Gtk.Align.START)
        self.osd_label = Gtk.Label()
        self.osd_label.get_style_context().add_class("osd-text")
        self.osd_box.add(self.osd_label)
        self.osd_box.set_no_show_all(True)
        self.video_container.add_overlay(self.osd_box)

        # 2) 전체화면 플로팅 컨트롤 바 오버레이 (화면 하단)
        self.fs_controls_box = self.build_fs_controls()
        self.fs_controls_box.set_halign(Gtk.Align.FILL)
        self.fs_controls_box.set_valign(Gtk.Align.END)
        self.fs_controls_box.set_no_show_all(True)
        self.video_container.add_overlay(self.fs_controls_box)

        self.main_paned.pack1(self.video_container, resize=True, shrink=False)
        self.sidebar = self.build_playlist_panel()
        self.main_paned.pack2(self.sidebar, resize=True, shrink=False)
        self.main_paned.connect("notify::position", self.on_paned_notify_position)
        self.main_paned.connect("size-allocate", self.on_paned_size_allocate)
        root.pack_start(self.main_paned, True, True, 0)

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

        # 속도 조절 버튼 ([-] 1.0x [+])
        speed_down_btn = Gtk.Button(label="˗")
        speed_down_btn.set_tooltip_text("재생 속도 감소 (단축키: Down 또는 a)")
        speed_down_btn.connect("clicked", lambda _b: self.step_playback_rate(-0.25))
        actions.pack_start(speed_down_btn, False, False, 0)

        self.speed_button = Gtk.Button(label="1.0x")
        self.speed_button.get_style_context().add_class("speed-btn")
        self.speed_button.set_tooltip_text("재생 속도 설정 (단축키: Up/Down 또는 d/a, r: 1.0x)")
        self.speed_button.connect("clicked", self.on_speed_button_clicked)
        actions.pack_start(self.speed_button, False, False, 0)

        speed_up_btn = Gtk.Button(label="˖")
        speed_up_btn.set_tooltip_text("재생 속도 증가 (단축키: Up 또는 d)")
        speed_up_btn.connect("clicked", lambda _b: self.step_playback_rate(0.25))
        actions.pack_start(speed_up_btn, False, False, 0)

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
        panel.set_size_request(240, -1)
        panel.set_border_width(12)

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="재생목록", xalign=0)
        title.get_style_context().add_class("section-title")
        count = Gtk.Label(label=f"{len(self.playlist)}개 영상", xalign=1)
        count.get_style_context().add_class("muted")
        heading.pack_start(title, True, True, 0)
        heading.pack_end(count, False, False, 0)
        panel.pack_start(heading, False, False, 2)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if not self.is_single_file_mode:
            exp_btn = Gtk.Button(label="전체 펼치기")
            exp_btn.get_style_context().add_class("tree-tool-btn")
            exp_btn.set_tooltip_text("모든 폴더 펼치기")
            exp_btn.connect("clicked", lambda _b: self.playlist_treeview.expand_all())
            col_btn = Gtk.Button(label="전체 접기")
            col_btn.get_style_context().add_class("tree-tool-btn")
            col_btn.set_tooltip_text("모든 폴더 접기")
            col_btn.connect("clicked", lambda _b: self.collapse_playlist_tree())
            tools.pack_start(exp_btn, True, True, 0)
            tools.pack_start(col_btn, True, True, 0)

        self.wrap_button = Gtk.Button(label="줄바꿈")
        self.wrap_button.get_style_context().add_class("tree-tool-btn")
        self.wrap_button.set_tooltip_text("긴 파일명 자동 줄바꿈 켜기/끄기")
        self.wrap_button.connect("clicked", self.on_wrap_toggle)
        if self.is_single_file_mode:
            tools.pack_start(self.wrap_button, True, True, 0)
        else:
            tools.pack_start(self.wrap_button, False, False, 0)
        panel.pack_start(tools, False, False, 2)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.tree_store = Gtk.TreeStore(str, str, str, int, bool)
        self.playlist_treeview = Gtk.TreeView(model=self.tree_store)
        self.playlist_treeview.set_headers_visible(False)
        self.playlist_treeview.set_activate_on_single_click(True)
        self.playlist_treeview.set_has_tooltip(True)
        self.playlist_treeview.connect("query-tooltip", self.on_tree_query_tooltip)
        self.playlist_treeview.connect("size-allocate", self.on_tree_size_allocate)
        self.playlist_treeview.connect("row-activated", self.on_tree_row_activated)
        self.playlist_treeview.connect("row-expanded", self.on_tree_row_expanded)
        self.playlist_treeview.connect("row-collapsed", self.on_tree_row_collapsed)

        col = Gtk.TreeViewColumn("Track")
        r_icon = Gtk.CellRendererText()
        r_icon.set_property("xpad", 4)
        col.pack_start(r_icon, False)
        col.add_attribute(r_icon, "text", 0)

        self.r_text = Gtk.CellRendererText()
        self.r_text.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.r_text.set_property("ypad", 6)
        col.pack_start(self.r_text, True)
        col.add_attribute(self.r_text, "markup", 1)
        self.playlist_treeview.append_column(col)

        self.populate_playlist_tree()

        scroll.add(self.playlist_treeview)
        panel.pack_start(scroll, True, True, 0)
        return panel

    def on_paned_notify_position(self, paned, _gparam):
        """사용자가 스플리터 핸들을 드래그할 때 사이드바 너비를 기억합니다."""
        if self.is_adjusting_paned or not self.sidebar or not self.sidebar.get_visible():
            return
        pos = paned.get_position()
        alloc_w = paned.get_allocation().width
        if alloc_w > 0 and pos > 0:
            current_s_w = alloc_w - pos
            if current_s_w >= 200:
                self.sidebar_width = current_s_w

    def on_paned_size_allocate(self, paned, allocation):
        """창 크기 조절 시 사이드바의 설정된 너비를 정확히 유지합니다."""
        if not self.sidebar or not self.sidebar.get_visible():
            return
        target_pos = max(200, allocation.width - self.sidebar_width)
        if abs(paned.get_position() - target_pos) > 2:
            self.is_adjusting_paned = True
            paned.set_position(target_pos)
            self.is_adjusting_paned = False

    def on_wrap_toggle(self, _button):
        """재생목록 내 긴 파일명의 자동 줄바꿈을 토글합니다."""
        self.is_wrap_enabled = not self.is_wrap_enabled
        if not self.r_text:
            return
        if self.is_wrap_enabled:
            if self.wrap_button:
                self.wrap_button.get_style_context().add_class("active")
            self.r_text.set_property("wrap-mode", Pango.WrapMode.WORD_CHAR)
            self.r_text.set_property("ellipsize", Pango.EllipsizeMode.NONE)
            self.update_tree_wrap_width()
        else:
            if self.wrap_button:
                self.wrap_button.get_style_context().remove_class("active")
            self.r_text.set_property("ellipsize", Pango.EllipsizeMode.END)
            self.r_text.set_property("wrap-width", -1)
        if self.playlist_treeview:
            self.playlist_treeview.queue_resize()

    def update_tree_wrap_width(self):
        """트리뷰 너비에 맞춰 셀 렌더러의 wrap-width를 자동 계산합니다."""
        if not self.is_wrap_enabled or not self.playlist_treeview or not self.r_text:
            return
        alloc = self.playlist_treeview.get_allocation()
        if alloc.width > 50:
            target_w = max(120, alloc.width - 65)
            if self.r_text.get_property("wrap-width") != target_w:
                self.r_text.set_property("wrap-width", target_w)

    def on_tree_size_allocate(self, _widget, allocation):
        """트리뷰 크기 변경 시 줄바꿈 너비를 실시간 동기화합니다."""
        if self.is_wrap_enabled and self.r_text:
            target_w = max(120, allocation.width - 65)
            if self.r_text.get_property("wrap-width") != target_w:
                self.r_text.set_property("wrap-width", target_w)

    def on_tree_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        """재생목록 항목에 마우스 호버 시 전체 파일명 및 경로를 툴팁으로 표시합니다."""
        res = widget.get_tooltip_context(x, y, keyboard_mode)
        if not res:
            return False
        bool_val, bx, by, model, path, tree_iter = res
        if not bool_val or tree_iter is None:
            return False

        try:
            is_dir = model.get_value(tree_iter, 4)
            full_path = model.get_value(tree_iter, 2)
            idx = model.get_value(tree_iter, 3)

            if is_dir:
                dir_name = os.path.basename(full_path)
                safe_name = GLib.markup_escape_text(dir_name)
                safe_path = GLib.markup_escape_text(full_path)
                tooltip.set_markup(
                    f"📁 <b>{safe_name}</b>\n"
                    f"<span color='#8f98a8' size='smaller'>{safe_path}</span>"
                )
            else:
                file_name = os.path.basename(full_path)
                safe_name = GLib.markup_escape_text(file_name)
                safe_path = GLib.markup_escape_text(full_path)
                num_badge = f"<span color='#e9ff5b' weight='bold'>#{idx + 1}</span> " if idx >= 0 else ""
                tooltip.set_markup(
                    f"🎬 {num_badge}<b>{safe_name}</b>\n"
                    f"<span color='#8f98a8' size='smaller'>{safe_path}</span>"
                )
            widget.set_tooltip_row(tooltip, path)
            return True
        except Exception:
            return False

    def on_playlist_toggle(self, _button):
        is_vis = not self.sidebar.get_visible()
        self.sidebar.set_visible(is_vis)
        if is_vis and self.main_paned:
            alloc_w = self.main_paned.get_allocation().width
            if alloc_w > 0:
                self.main_paned.set_position(max(200, alloc_w - self.sidebar_width))

    def populate_playlist_tree(self):
        """재생목록을 디렉토리 계층 구조의 트리로 구축합니다."""
        if not self.tree_store:
            return
        self.tree_store.clear()
        self.playlist_tree_iters.clear()

        abs_root = os.path.abspath(self.input_path) if os.path.isdir(self.input_path) else None

        if not abs_root:
            for idx, p in enumerate(self.playlist):
                fname = os.path.basename(p)
                safe_name = GLib.markup_escape_text(fname)
                v_iter = self.tree_store.append(
                    None,
                    ["🎬", f"<span>{safe_name}</span>", p, idx, False]
                )
                self.playlist_tree_iters[idx] = v_iter
            return

        # 1. 디렉토리별 하위 영상 파일 수 카운트
        dir_counts = {}
        for p in self.playlist:
            rel_p = os.path.relpath(p, abs_root)
            parts = rel_p.split(os.sep)[:-1]
            for i in range(1, len(parts) + 1):
                d = os.sep.join(parts[:i])
                dir_counts[d] = dir_counts.get(d, 0) + 1

        # 2. 계층형 폴더 및 비디오 노드 추가
        dir_iters = {}
        for idx, p in enumerate(self.playlist):
            rel_p = os.path.relpath(p, abs_root)
            parts = rel_p.split(os.sep)
            fname = parts[-1]
            dir_parts = parts[:-1]

            cur_p = ""
            parent_iter = None
            for d in dir_parts:
                cur_p = os.path.join(cur_p, d) if cur_p else d
                if cur_p not in dir_iters:
                    cnt = dir_counts.get(cur_p, 0)
                    safe_d = GLib.markup_escape_text(d)
                    lbl = f"<b>{safe_d}</b> <span color='#70798a' size='smaller'>({cnt})</span>"
                    d_iter = self.tree_store.append(
                        parent_iter,
                        ["📁", lbl, cur_p, -1, True]
                    )
                    dir_iters[cur_p] = d_iter
                    parent_iter = d_iter
                else:
                    parent_iter = dir_iters[cur_p]

            safe_name = GLib.markup_escape_text(fname)
            v_iter = self.tree_store.append(
                parent_iter,
                ["🎬", f"<span>{safe_name}</span>", p, idx, False]
            )
            self.playlist_tree_iters[idx] = v_iter

    def on_playlist_toggle(self, _button):
        self.sidebar.set_visible(not self.sidebar.get_visible())

    def on_tree_row_activated(self, treeview, path, _column):
        """트리 항목 클릭 시: 폴더는 펼치기/접기 토글, 비디오 파일은 즉시 재생"""
        model = treeview.get_model()
        tree_iter = model.get_iter(path)
        is_dir = model.get_value(tree_iter, 4)
        if is_dir:
            if treeview.row_expanded(path):
                treeview.collapse_row(path)
            else:
                treeview.expand_row(path, False)
        else:
            idx = model.get_value(tree_iter, 3)
            if idx != self.current_index and 0 <= idx < len(self.playlist):
                self.current_index = idx
                self.play_current_video()

    def on_tree_row_expanded(self, _treeview, tree_iter, _path):
        if self.tree_store and self.tree_store.get_value(tree_iter, 4):
            self.tree_store.set_value(tree_iter, 0, "📂")

    def on_tree_row_collapsed(self, _treeview, tree_iter, _path):
        if self.tree_store and self.tree_store.get_value(tree_iter, 4):
            self.tree_store.set_value(tree_iter, 0, "📁")

    def collapse_playlist_tree(self):
        """전체 폴더를 접되, 현재 재생 중인 영상의 폴더는 열어둡니다."""
        if self.playlist_treeview:
            self.playlist_treeview.collapse_all()
            if 0 <= self.current_index < len(self.playlist):
                cur_iter = self.playlist_tree_iters.get(self.current_index)
                if cur_iter and self.tree_store.iter_is_valid(cur_iter):
                    path = self.tree_store.get_path(cur_iter)
                    self.playlist_treeview.expand_to_path(path)
                    self.playlist_treeview.scroll_to_cell(path, None, True, 0.5, 0.0)

    def refresh_playlist_ui(self):
        if not self.playlist:
            return
        current_path = self.playlist[self.current_index]
        abs_root = os.path.abspath(self.input_path) if os.path.isdir(self.input_path) else None
        if abs_root:
            display_name = os.path.relpath(current_path, abs_root)
        else:
            display_name = os.path.basename(current_path)

        self.now_playing_label.set_text(
            f"재생 중  ·  {display_name}   {self.current_index + 1}/{len(self.playlist)}"
        )
        self.now_playing_label.set_tooltip_text(f"{display_name}\n({current_path})")

        if not self.tree_store or not self.playlist_tree_iters:
            return

        active_iter = None
        for idx, tree_iter in self.playlist_tree_iters.items():
            if not self.tree_store.iter_is_valid(tree_iter):
                continue
            path_val = self.tree_store.get_value(tree_iter, 2)
            fname = os.path.basename(path_val)
            safe_name = GLib.markup_escape_text(fname)

            if idx == self.current_index:
                active_iter = tree_iter
                self.tree_store.set_value(tree_iter, 0, "▶")
                self.tree_store.set_value(
                    tree_iter,
                    1,
                    f"<span color='#e9ff5b' weight='bold'>{safe_name}</span>"
                )
            else:
                self.tree_store.set_value(tree_iter, 0, "🎬")
                self.tree_store.set_value(
                    tree_iter,
                    1,
                    f"<span color='#dce2ec'>{safe_name}</span>"
                )

        if active_iter and self.playlist_treeview:
            tree_path = self.tree_store.get_path(active_iter)
            if tree_path:
                self.playlist_treeview.expand_to_path(tree_path)
                sel = self.playlist_treeview.get_selection()
                sel.select_iter(active_iter)
                GLib.idle_add(lambda: self.playlist_treeview.scroll_to_cell(tree_path, None, True, 0.5, 0.0))

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
        if position_ok and position > 0:
            self.last_known_pos_ns = position
        pos_sec = int(position / Gst.SECOND) if position_ok else -1

        # 초(second) 단위가 바뀌었을 때만 GTK UI를 갱신하여 X11 Re-draw 부하 제거
        if position_ok and pos_sec != self.last_ui_pos_sec:
            self.last_ui_pos_sec = pos_sec
            time_str = self.format_time(position)

            # 1) 일반 모드 컨트롤 UI 갱신
            if not self.is_video_only:
                self.position_label.set_text(time_str)
                if self.duration_ns == 0:
                    duration_ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
                    if duration_ok and duration > 0:
                        self.duration_ns = duration
                        self.duration_label.set_text(self.format_time(duration))
                if self.duration_ns > 0 and not self.is_seeking:
                    self.progress_scale.set_value(min(100, position * 100 / self.duration_ns))

            # 2) 전체화면 플로팅 컨트롤 UI 갱신
            if getattr(self, "fs_position_label", None):
                self.fs_position_label.set_text(time_str)
            if getattr(self, "fs_duration_label", None):
                if self.duration_ns > 0:
                    self.fs_duration_label.set_text(self.format_time(self.duration_ns))
            if getattr(self, "fs_progress_scale", None) and self.duration_ns > 0 and not self.is_seeking:
                self.fs_progress_scale.set_value(min(100, position * 100 / self.duration_ns))

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
            self.last_known_pos_ns = target
            self.pipeline.seek(
                self.playback_rate,
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                Gst.SeekType.SET,
                target,
                Gst.SeekType.NONE,
                -1
            )
            self.show_osd(f"⏱️ {self.format_time(target)} / {self.format_time(self.duration_ns)}")
        self.is_seeking = False
        return False

    def on_volume_changed(self, scale):
        val = scale.get_value()
        if hasattr(self, "fs_volume_scale") and abs(self.fs_volume_scale.get_value() - val) > 0.5:
            self.fs_volume_scale.set_value(val)
        if self.pipeline:
            self.pipeline.set_property("volume", val / 100.0)

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
        """마우스 움직임 감지 시 커서를 표시하고 전체화면일 때 컨트롤 바를 띄운 후 2.5초 후 자동 숨김 타이머를 재설정합니다."""
        if self.is_video_only:
            if self.is_cursor_hidden:
                self.show_cursor()
            if getattr(self, "fs_controls_box", None) and not self.is_fs_controls_visible:
                self.fs_controls_box.show_all()
                self.is_fs_controls_visible = True

            if getattr(self, "cursor_hide_timer_id", None):
                try:
                    GLib.source_remove(self.cursor_hide_timer_id)
                except Exception:
                    pass
            self.cursor_hide_timer_id = GLib.timeout_add(2500, self._on_hide_timer_tick)
        return False

    def _on_hide_timer_tick(self):
        """2.5초 동안 마우스 조작이 없을 때 전체화면 컨트롤 바와 커서를 숨깁니다."""
        if self.is_video_only:
            if getattr(self, "is_mouse_over_fs_controls", False) or getattr(self, "is_popover_open", False):
                return True
            if getattr(self, "fs_controls_box", None) and self.is_fs_controls_visible:
                self.fs_controls_box.hide()
                self.is_fs_controls_visible = False
            self.hide_cursor()
        self.cursor_hide_timer_id = None
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
            if getattr(self, "fs_controls_box", None):
                self.fs_controls_box.hide()
                self.is_fs_controls_visible = False
            self.fullscreen()
            self.set_keep_above(True)
            self.is_fullscreen = True
            self.is_video_only = True
            self.fullscreen_button.set_label("⧉")
            # 전체화면 전환 시 마우스 커서 즉시 숨김
            self.hide_cursor()
            self.show_osd("🖥️ 전체화면 (영상 전용)")
            print("🖥️ 영상 전용 전체화면 (마우스 조작 시 컨트롤 표시)")
        else:
            self.topbar.show()
            self.controls.show()
            if self.sidebar_was_visible:
                self.sidebar.show()
                if self.main_paned:
                    alloc_w = self.main_paned.get_allocation().width
                    if alloc_w > 0:
                        self.main_paned.set_position(max(200, alloc_w - self.sidebar_width))
            if getattr(self, "fs_controls_box", None):
                self.fs_controls_box.hide()
                self.is_fs_controls_visible = False
            self.is_video_only = False
            self.fullscreen_button.set_label("⛶")
            # 일반 모드 복귀 시 마우스 커서 복원
            self.show_cursor()
            self.show_osd("🖥️ 창 모드 복귀")
            print("🖥️ 플레이어 UI 표시")

    def get_current_subtitle_font_desc(self):
        """
        한국어(KR), 중국어 번체/대만어(TC), 간체(SC), 일본어(JP), 영문 알파벳을
        한 글자의 빠짐이나 깨짐 없이 100% 온전하게 렌더링하는 CJK 통합 폰트 디스크립터를 반환합니다.
        """
        active_indices = getattr(self, "active_subtitle_indices", set())
        
        num_tracks = len(active_indices) if active_indices else 1
        if num_tracks <= 1:
            base_pt = 22
        elif num_tracks == 2:
            base_pt = 17
        else:
            base_pt = 14
        final_pt = max(10, min(36, int(base_pt * getattr(self, "subtitle_font_scale", 1.0))))
        
        # Noto Sans CJK TC는 대만 번체 한자(13,053자)와 한글(11,172자), 영문, 기호를 단일 폰트 내에 100% 내장하고 있어
        # 한국어 단독, 중국어 단독, 한국어+중국어+영어 다중 자막 어떤 조합에서도 폰트 폴백 결함 없이 완벽히 렌더링됩니다.
        font_stack = "Noto Sans CJK TC, Noto Sans CJK KR, Noto Sans CJK SC, Noto Sans CJK JP, Sans"
        return f"{font_stack} Bold {final_pt}"

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

    def check_video_hw_support(self, file_path):
        """
        ffprobe JSON 정보를 분석하여 Jetson NVDEC 하드웨어 디코더가
        100% 안정적으로 가속 지원하는 포맷(H.265/HEVC 및 H.264 8-bit)인지 판정합니다.
        JetPack 드라이버 상 DPB/버퍼 결함이 발생하는 AV1, VP9 등의 코덱이나
        H.264 10-bit 영상은 미지원으로 분류하여 H.265로 자동 변환하도록 유도합니다.
        영구 캐시(hw_cache)를 우선 조회하여 불필요한 ffprobe 중복 실행을 차단합니다.
        """
        cached = hw_cache.get(file_path)
        if cached is not None:
            return cached

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
                res = (False, "비디오 스트림 없음")
                hw_cache.set(file_path, res[0], res[1])
                return res
            stream = data["streams"][0]
            codec = stream.get("codec_name", "").lower()
            pix_fmt = stream.get("pix_fmt", "").lower()
            profile = stream.get("profile", "").lower()

            # 1. H.265 / HEVC -> 8-bit 및 10-bit 모두 Jetson NVDEC 하드웨어 가속 100% 완벽 지원
            if codec in ["hevc", "h265"]:
                bit_depth = "10-bit" if "10" in pix_fmt or "p10" in pix_fmt else "8-bit"
                res = (True, f"HEVC ({codec.upper()}) {bit_depth} NVDEC 지원")
                hw_cache.set(file_path, res[0], res[1])
                return res

            # 2. H.264 / AVC -> 8-bit만 지원 (High 10 / yuv420p10le 등 10-bit는 NVDEC 미지원)
            if codec in ["h264", "avc"]:
                if "10" in pix_fmt or "10" in profile or "p10" in pix_fmt:
                    res = (False, f"H.264 10-bit NVDEC 미지원 ({pix_fmt}/{profile})")
                else:
                    res = (True, "H.264 8-bit NVDEC 지원")
                hw_cache.set(file_path, res[0], res[1])
                return res

            # 3. 그 외 (AV1, VP9, VP8 등) -> JetPack nvv4l2decoder DPB 결함 및 SW 디코딩 병목 방지를 위해 H.265 변환 대상
            res = (False, f"NVDEC 미지원/불안정 코덱 ({codec.upper()})")
            hw_cache.set(file_path, res[0], res[1])
            return res
        except Exception as e:
            res = (False, f"코덱 분석 실패 ({e})")
            return res

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
                hw_cache.set(file_path, True, "기존 H.265 변환본")
                hw_cache.save()
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
            hw_cache.set(target_mp4_path, True, f"HEVC 변환 완료 ({pix_fmt})")
            hw_cache.set(file_path, True, "H.265 변환 완료")
            hw_cache.save()
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
                for root, dirs, files in os.walk(abs_path, followlinks=True):
                    # 백업 디렉토리(unsupported_originals) 및 숨김 폴더는 탐색에서 제외
                    dirs[:] = sorted([d for d in dirs if d != "unsupported_originals" and not d.startswith('.')])
                    files.sort()
                    for fname in files:
                        if fname.startswith('.'):
                            continue
                        _stem, ext = os.path.splitext(fname)
                        if ext.lower() in video_exts:
                            full_p = os.path.join(root, fname)
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

        mode_str = "단일 파일 반복 모드" if self.is_single_file_mode else "폴더 순환 모드"
        print(f"📂 [{mode_str}] 총 {len(self.playlist)}개의 영상을 로드했습니다.")
        for idx, path in enumerate(self.playlist):
            disp = os.path.relpath(path, abs_path) if not self.is_single_file_mode else os.path.basename(path)
            print(f"   [{idx}] {disp}")

    def on_realize(self, widget):
        """GTK 창의 리소스가 로드되었을 때 영상 재생을 시작하고 백그라운드 검사기를 가동합니다."""
        if self.pipeline is not None:
            return
        print("🖥️ GUI 창 준비 완료. 영상 재생을 시작합니다.")
        
        top_window = self.get_window()
        if top_window:
            enable_x11_compositor_bypass(top_window)

        self.play_current_video()
        self.start_background_hw_checker()

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
                        GLib.idle_add(self._apply_background_h265_path, idx, target_h265)
                # 현재 영상 재생 성능에 영향을 주지 않도록 파일 간 0.05초 대기
                time.sleep(0.05)

        hw_cache.save()

    def _apply_background_h265_path(self, idx, new_path):
        if 0 <= idx < len(self.playlist) and os.path.exists(new_path):
            self.playlist[idx] = new_path
            self.update_playlist_item_ui(idx, new_path)

    def update_playlist_item_ui(self, idx, new_path):
        """재생목록 항목 경로가 변경(H.265 변환 등)되었을 때 트리뷰 UI를 동기화합니다."""
        if not self.tree_store or idx not in self.playlist_tree_iters:
            return
        tree_iter = self.playlist_tree_iters[idx]
        if self.tree_store.iter_is_valid(tree_iter):
            fname = os.path.basename(new_path)
            safe_name = GLib.markup_escape_text(fname)
            self.tree_store.set_value(tree_iter, 1, f"<span>{safe_name}</span>")
            self.tree_store.set_value(tree_iter, 2, new_path)

    def play_current_video(self, start_position_ns=0):
        """[성능 최적화] 영상 전환 및 다중 자막 변경 시 파이프라인 자원을 완전 세척 후 신규 구축합니다."""
        if not self.playlist or self.current_index < 0 or self.current_index >= len(self.playlist):
            return

        video_path = self.playlist[self.current_index]
        self.rate_applied_on_preroll = False

        # [On-Demand 하드웨어 적합성 검사 및 안전 변환]
        if os.path.exists(video_path):
            is_supported, reason = self.check_video_hw_support(video_path)
            if not is_supported:
                print(f"⚠️ [하드웨어 미지원 코덱 감지] {os.path.basename(video_path)}: {reason}")
                converted_path = self.auto_convert_to_h265(video_path)
                if converted_path != video_path and os.path.exists(converted_path):
                    self.playlist[self.current_index] = converted_path
                    video_path = converted_path
                    self.update_playlist_item_ui(self.current_index, converted_path)
        
        if start_position_ns == 0:
            abs_root = os.path.abspath(self.input_path) if os.path.isdir(self.input_path) else None
            disp = os.path.relpath(video_path, abs_root) if abs_root else os.path.basename(video_path)
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
                # 영상이 새로 재생될 때 모든 언어 자막을 기본으로 모두 불러와서 다중 표출
                self.active_subtitle_indices = set(range(len(self.available_subtitles)))
                self.has_subtitles = True
                self.subtitles_enabled = True
                print(f"💬 [다중 자막 자동 활성화 ({len(self.available_subtitles)}개)] " + ", ".join([s['label'] for s in self.available_subtitles]))
            else:
                self.has_subtitles = False

        self.pending_seek_ns = start_position_ns
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

        elif message.type == Gst.MessageType.ASYNC_DONE:
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

    def build_subtitle_popover(self, parent_btn=None):
        """다중 자막 선택, 크기 조절 및 싱크 조절 팝오버(Popover) 창을 구성합니다."""
        target_btn = parent_btn or (self.fs_sub_button if self.is_video_only and getattr(self, "fs_sub_button", None) else self.sub_button)
        self.sub_popover = Gtk.Popover(relative_to=target_btn)
        self.sub_popover.set_position(Gtk.PositionType.TOP)
        self.sub_popover.set_border_width(12)
        
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # 헤더
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="💬 자막 선택 & 설정", xalign=0)
        title.get_style_context().add_class("popover-title")
        header.pack_start(title, True, True, 0)
        container.pack_start(header, False, False, 2)
        
        hint = Gtk.Label(label="다중 자막 선택 시 언어별 뱃지와 함께 동시에 표시됩니다.", xalign=0)
        hint.get_style_context().add_class("muted")
        container.pack_start(hint, False, False, 0)
        
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        container.pack_start(sep1, False, False, 2)

        # 🗚 자막 크기 조절 바
        size_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        size_bar.get_style_context().add_class("sub-btn-row")
        
        size_lbl = Gtk.Label(label="🗚 크기:")
        size_lbl.get_style_context().add_class("muted")
        size_bar.pack_start(size_lbl, False, False, 0)
        
        dec_btn = Gtk.Button(label="작게 (-)")
        dec_btn.set_tooltip_text("자막 크기 축소 (단축키: [ )")
        dec_btn.connect("clicked", lambda _b: self.adjust_subtitle_scale(-0.1))
        size_bar.pack_start(dec_btn, True, True, 0)
        
        pct_str = f"{int(self.subtitle_font_scale * 100)}%"
        self.scale_label = Gtk.Label(label=pct_str)
        self.scale_label.set_width_chars(5)
        size_bar.pack_start(self.scale_label, False, False, 2)
        
        inc_btn = Gtk.Button(label="크게 (+)")
        inc_btn.set_tooltip_text("자막 크기 확대 (단축키: ] )")
        inc_btn.connect("clicked", lambda _b: self.adjust_subtitle_scale(0.1))
        size_bar.pack_start(inc_btn, True, True, 0)
        
        reset_size_btn = Gtk.Button(label="100%")
        reset_size_btn.set_tooltip_text("기본 크기(100%)로 복원")
        reset_size_btn.connect("clicked", self.reset_subtitle_scale)
        size_bar.pack_start(reset_size_btn, False, False, 0)
        
        container.pack_start(size_bar, False, False, 2)

        # ⏱️ 자막 싱크(Sync) 조절 바
        sync_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sync_bar.get_style_context().add_class("sub-btn-row")
        
        sync_lbl = Gtk.Label(label="⏱️ 싱크:")
        sync_lbl.get_style_context().add_class("muted")
        sync_bar.pack_start(sync_lbl, False, False, 0)
        
        fast_btn = Gtk.Button(label="-0.5s")
        fast_btn.set_tooltip_text("자막 0.5초 빠르게 (단축키: Z, ,: -0.1s)")
        fast_btn.connect("clicked", lambda _b: self.adjust_subtitle_sync(-500))
        sync_bar.pack_start(fast_btn, True, True, 0)
        
        sync_str = f"{self.subtitle_offset_ms / 1000:+.1f}s"
        self.sync_label = Gtk.Label(label=sync_str)
        self.sync_label.set_width_chars(6)
        sync_bar.pack_start(self.sync_label, False, False, 2)
        
        slow_btn = Gtk.Button(label="+0.5s")
        slow_btn.set_tooltip_text("자막 0.5초 느리게 (단축키: X, .: +0.1s)")
        slow_btn.connect("clicked", lambda _b: self.adjust_subtitle_sync(500))
        sync_bar.pack_start(slow_btn, True, True, 0)
        
        reset_sync_btn = Gtk.Button(label="0.0s")
        reset_sync_btn.set_tooltip_text("자막 싱크 기본값(0.0초)으로 복원")
        reset_sync_btn.connect("clicked", self.reset_subtitle_sync)
        sync_bar.pack_start(reset_sync_btn, False, False, 0)
        
        container.pack_start(sync_bar, False, False, 2)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        container.pack_start(sep2, False, False, 2)

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

        def on_sub_pop_closed(_pop):
            self.is_popover_open = False
        self.sub_popover.connect("closed", on_sub_pop_closed)

    def adjust_subtitle_scale(self, delta):
        """자막 크기를 delta만큼 확대/축소하고 즉시 화면에 반영합니다."""
        new_scale = round(max(0.6, min(1.6, self.subtitle_font_scale + delta)), 2)
        if new_scale != self.subtitle_font_scale:
            self.subtitle_font_scale = new_scale
            pct = int(self.subtitle_font_scale * 100)
            print(f"🗚 [자막 크기 조절] {pct}%")
            self.show_osd(f"🗚 자막 크기: {pct}%")
            if getattr(self, "scale_label", None):
                self.scale_label.set_text(f"{pct}%")
            if getattr(self, "subtitle_overlay_element", None):
                try:
                    self.subtitle_overlay_element.set_property("font-desc", self.get_current_subtitle_font_desc())
                except Exception:
                    pass
            self.reload_and_apply_subtitles()

    def reset_subtitle_scale(self, _btn=None):
        """자막 크기를 기본값(100%)으로 복원합니다."""
        if self.subtitle_font_scale != 1.0:
            self.subtitle_font_scale = 1.0
            print("🗚 [자막 크기 조절] 100% (기본값)")
            self.show_osd("🗚 자막 크기: 100%")
            if getattr(self, "scale_label", None):
                self.scale_label.set_text("100%")
            if getattr(self, "subtitle_overlay_element", None):
                try:
                    self.subtitle_overlay_element.set_property("font-desc", self.get_current_subtitle_font_desc())
                except Exception:
                    pass
            self.reload_and_apply_subtitles()

    def adjust_subtitle_sync(self, delta_ms):
        """자막 싱크를 delta_ms만큼 앞당기거나 늦추고 즉시 화면에 반영합니다."""
        self.subtitle_offset_ms += delta_ms
        sec_str = f"{self.subtitle_offset_ms / 1000:+.1f}s"
        print(f"⏱️ [자막 싱크 조절] {sec_str}")
        self.show_osd(f"⏱️ 자막 싱크: {sec_str}")
        if getattr(self, "sync_label", None):
            self.sync_label.set_text(sec_str)
        self.reload_and_apply_subtitles()

    def reset_subtitle_sync(self, _btn=None):
        """자막 싱크를 기본값(0.0초)으로 복원합니다."""
        if self.subtitle_offset_ms != 0:
            self.subtitle_offset_ms = 0
            print("⏱️ [자막 싱크 조절] 0.0s (기본값)")
            self.show_osd("⏱️ 자막 싱크: 0.0s")
            if getattr(self, "sync_label", None):
                self.sync_label.set_text("0.0s")
            self.reload_and_apply_subtitles()

    def show_subtitle_popover(self, parent_btn=None):
        """자막 선택 팝오버를 열거나 닫습니다."""
        if not self.available_subtitles:
            print("ℹ️ 현재 영상에 사용 가능한 자막이 없습니다.")
            return
        if self.sub_popover:
            self.sub_popover.destroy()
            self.sub_popover = None
        self.build_subtitle_popover(parent_btn=parent_btn)
        self.is_popover_open = True
        self.sub_popover.show_all()
        self.sub_popover.popup()

    def on_sub_button_clicked(self, widget):
        """자막 버튼 클릭 시 단일 자막은 토글, 다중 자막은 팝오버 메뉴를 표시합니다."""
        if not self.available_subtitles:
            return
        if len(self.available_subtitles) == 1:
            self.toggle_subtitles()
        else:
            self.show_subtitle_popover(parent_btn=widget)

    def on_subtitle_checkbox_toggled(self, chk_button, track_idx):
        """자막 체크박스 토글 시 실시간으로 활성 자막 목록을 갱신하고 화면에 안전하게 반영합니다."""
        if getattr(self, "is_updating_sub_checkboxes", False):
            return
            
        if chk_button.get_active():
            self.active_subtitle_indices.add(track_idx)
            self.subtitles_enabled = True
        else:
            self.active_subtitle_indices.discard(track_idx)
            if not self.active_subtitle_indices:
                self.subtitles_enabled = False
        self.schedule_subtitles_reload()

    def on_select_all_subtitles(self, _btn):
        """모든 자막 체크 활성화 (일괄 락 적용으로 프로그램 충돌 및 중복 리로드 차단)"""
        self.is_updating_sub_checkboxes = True
        try:
            self.active_subtitle_indices = set(range(len(self.available_subtitles)))
            self.subtitles_enabled = bool(self.active_subtitle_indices)
            for chk in getattr(self, "sub_checkboxes", []):
                chk.set_active(True)
        finally:
            self.is_updating_sub_checkboxes = False
        self.schedule_subtitles_reload()

    def on_deselect_all_subtitles(self, _btn):
        """모든 자막 체크 해제 (일괄 락 적용으로 프로그램 충돌 및 중복 리로드 차단)"""
        self.is_updating_sub_checkboxes = True
        try:
            self.active_subtitle_indices.clear()
            self.subtitles_enabled = False
            for chk in getattr(self, "sub_checkboxes", []):
                chk.set_active(False)
        finally:
            self.is_updating_sub_checkboxes = False
        self.schedule_subtitles_reload()

    def schedule_subtitles_reload(self):
        """빠른 체크박스 연타나 일괄 변경 시 파이프라인 중복 파괴를 막기 위해 50ms 디바운스로 안전하게 재로드합니다."""
        if getattr(self, "sub_reload_timer_id", None):
            try:
                GLib.source_remove(self.sub_reload_timer_id)
            except Exception:
                pass
            self.sub_reload_timer_id = None
        self.sub_reload_timer_id = GLib.timeout_add(50, self._deferred_reload_subtitles)

    def _deferred_reload_subtitles(self):
        self.sub_reload_timer_id = None
        self.reload_and_apply_subtitles()
        return False

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
            merged_file = generate_merged_subtitle_file(
                active_tracks, video_path,
                font_scale=self.subtitle_font_scale,
                offset_ms=self.subtitle_offset_ms
            )
            new_suburi = f"file://{pathname2url(os.path.abspath(merged_file))}" if merged_file else None
        else:
            new_suburi = None
            
        # GStreamer playbin은 실행 중 suburi 변경 시 내부 파서를 다시 읽지 않으므로,
        # 자막 스트림이 변경된 경우 현재 재생 위치(초 단위)를 100% 보존하여 즉시 매끄럽게 재로드합니다.
        if new_suburi != getattr(self, "current_suburi", None):
            pos_ns = 0
            if self.pipeline:
                success, q_pos = self.pipeline.query_position(Gst.Format.TIME)
                if success and q_pos > 0:
                    pos_ns = q_pos
                elif getattr(self, "last_known_pos_ns", 0) > 0:
                    pos_ns = self.last_known_pos_ns
            self.play_current_video(start_position_ns=pos_ns)
        else:
            if not self.subtitles_enabled or not active_tracks:
                self.pipeline.set_property("current-text", -1)
            else:
                self.pipeline.set_property("current-text", 0)
                
        if getattr(self, "subtitle_overlay_element", None):
            try:
                self.subtitle_overlay_element.set_property("font-desc", self.get_current_subtitle_font_desc())
            except Exception:
                pass

        self.update_subtitle_button_ui()

    def update_subtitle_button_ui(self):
        """자막 버튼 레이블 및 활성화 상태 갱신 (일반 컨트롤 및 전체화면 컨트롤)"""
        btns = [b for b in [getattr(self, "sub_button", None), getattr(self, "fs_sub_button", None)] if b is not None]
        if not btns:
            return
            
        total = len(self.available_subtitles)
        if total == 0:
            for b in btns:
                b.set_label("💬 자막 없음")
                b.set_sensitive(False)
                b.set_tooltip_text("자막 없음")
        elif total == 1:
            lbl = "💬 자막 ON" if (self.subtitles_enabled and self.active_subtitle_indices) else "💬 자막 OFF"
            for b in btns:
                b.set_label(lbl)
                b.set_sensitive(True)
                b.set_tooltip_text("자막 켜기/끄기 (S)")
        else:
            active_cnt = len(self.active_subtitle_indices) if self.subtitles_enabled else 0
            lbl = f"💬 자막 ({active_cnt}/{total})"
            for b in btns:
                b.set_label(lbl)
                b.set_sensitive(True)
                b.set_tooltip_text(f"다중 자막 선택 메뉴 (S: 토글, C: 설정 창) - {total}개 사용 가능")

    def toggle_subtitles(self):
        """자막 켜기/끄기 상태를 토글합니다."""
        if not self.available_subtitles:
            print("ℹ️ 현재 영상에 로드된 자막이 없습니다.")
            return

        self.subtitles_enabled = not self.subtitles_enabled
        if self.subtitles_enabled and not self.active_subtitle_indices:
            self.active_subtitle_indices = set(range(len(self.available_subtitles)))

        status_str = "ON" if self.subtitles_enabled else "OFF"
        self.show_osd(f"💬 자막 {status_str}")
        self.reload_and_apply_subtitles()

    def on_key_press(self, widget, event):
        """키보드 입력 이벤트 제어"""
        keyname = Gdk.keyval_name(event.keyval)
        state = event.state
        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        
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
            delta = 30 if is_shift else 10
            self.seek_relative(delta)
            return True
        elif keyname == "Left":
            delta = -30 if is_shift else -10
            self.seek_relative(delta)
            return True
        elif keyname in ["l", "L"]:
            self.seek_relative(10)
            return True
        elif keyname in ["j", "J"]:
            self.seek_relative(-10)
            return True
        # 영상 재생 속도 제어
        elif keyname in ["Up", "d", "D"] or (is_shift and keyname in ["greater", "period"]):
            self.step_playback_rate(0.25)
            return True
        elif keyname in ["Down", "a", "A"] or (is_shift and keyname in ["less", "comma"]):
            self.step_playback_rate(-0.25)
            return True
        elif keyname in ["r", "R"]:
            self.reset_playback_rate()
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
        elif keyname in ["[", "bracketleft"]:
            self.adjust_subtitle_scale(-0.1)
            return True
        elif keyname in ["]", "bracketright"]:
            self.adjust_subtitle_scale(0.1)
            return True
        elif keyname in ["z", "Z"]:
            self.adjust_subtitle_sync(-500)
            return True
        elif keyname in ["x", "X"]:
            self.adjust_subtitle_sync(500)
            return True
        elif not is_shift and keyname in [",", "comma"]:
            self.adjust_subtitle_sync(-100)
            return True
        elif not is_shift and keyname in [".", "period"]:
            self.adjust_subtitle_sync(100)
            return True
        elif keyname in ["f", "F"]:
            self.toggle_fullscreen()
            return True
            
        return False

    def on_destroy(self, widget):
        self.is_destroyed = True
        try:
            hw_cache.save()
        except Exception:
            pass

        if getattr(self, "cursor_hide_timer_id", None):
            try:
                GLib.source_remove(self.cursor_hide_timer_id)
            except Exception:
                pass
            self.cursor_hide_timer_id = None
        self.show_cursor()

        if getattr(self, "osd_timer_id", None):
            try:
                GLib.source_remove(self.osd_timer_id)
            except Exception:
                pass
            self.osd_timer_id = None

        if getattr(self, "sub_reload_timer_id", None):
            try:
                GLib.source_remove(self.sub_reload_timer_id)
            except Exception:
                pass
            self.sub_reload_timer_id = None

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
