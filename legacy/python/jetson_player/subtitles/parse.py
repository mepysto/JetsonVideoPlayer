"""자막 파일(SMI/SRT/VTT/ASS) 탐색·파싱과 언어 감지"""
import hashlib
import html
import logging
import os
import re

from ..library import VIDEO_EXTS
from ..storage import CACHE_DIR
from .ass import events_as_plain, parse_ass

log = logging.getLogger(__name__)


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


AI_SUBTITLE_COLOR = "#B388FF"

# 영상 폴더에 쓸 수 없을 때(읽기 전용 공유 등) AI 자막·번역을 저장하는 곳
AI_SUBTITLE_CACHE_DIR = os.path.join(CACHE_DIR, "ai_subtitles")
SUBTITLE_EXTS = ('.srt', '.smi', '.vtt', '.ass', '.ssa', '.sub')


def cached_ai_subtitle_stem(video_path):
    """캐시 폴더용 이름: <영상 이름>.<폴더 해시 8자> — 다른 폴더의 같은 이름 영상과 섞이지 않게 합니다."""
    stem = os.path.splitext(os.path.basename(video_path))[0]
    folder = os.path.dirname(os.path.abspath(video_path))
    return f"{stem}.{hashlib.sha1(folder.encode('utf-8')).hexdigest()[:8]}"


def find_cached_ai_subtitles(video_path, cache_dir=None):
    """캐시 폴더에 저장된 이 영상의 자막 — AI 자막·번역·온라인에서 받은 자막
    (예전 버전이 해시 없이 저장한 <영상>.ai.<언어>.srt 포함)"""
    cache_dir = cache_dir or AI_SUBTITLE_CACHE_DIR
    stem = os.path.splitext(os.path.basename(video_path))[0]
    prefixes = (cached_ai_subtitle_stem(video_path) + ".", stem + ".ai.")
    try:
        names = sorted(os.listdir(cache_dir))
    except OSError:
        return []
    return [os.path.join(cache_dir, n) for n in names
            if n.startswith(prefixes) and n.lower().endswith(SUBTITLE_EXTS)]


def is_ai_subtitle(file_path):
    """플레이어가 생성한 AI 자막 파일(<영상>.ai.<언어>.srt)인지"""
    return ".ai." in os.path.basename(file_path).lower()


def get_subtitle_color(file_path, index=0):
    """자막 파일의 언어 태그를 분석하여 언어별 최적 고대비 고유 색상을 반환합니다."""
    stem = os.path.basename(file_path).lower()
    if is_ai_subtitle(file_path):
        return AI_SUBTITLE_COLOR
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
    """ASS / SSA 자막 텍스트를 [(start_ms, end_ms, text), ...] 목록으로 파싱합니다 (스타일은 버리고 글자만)."""
    return events_as_plain(parse_ass(content))


def load_ass_script(file_path):
    """ASS/SSA 파일의 스타일·위치 정보까지 담은 AssScript (ASS가 아니거나 읽지 못하면 None)"""
    if os.path.splitext(file_path or "")[1].lower() not in ('.ass', '.ssa'):
        return None
    try:
        content, _enc = read_subtitle_text(file_path)
        return parse_ass(content) if content else None
    except Exception as e:
        log.warning(f"⚠️ ASS 스타일 해석 실패 ({file_path}): {e}")
        return None


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
        log.warning(f"⚠️ 자막 파싱 실패 ({file_path}): {e}")
        return []


def get_subtitle_label(file_path):
    """자막 파일명에서 언어 태그를 감지하여 사람이 읽기 쉬운 레이블을 생성합니다."""
    base = os.path.basename(file_path)
    stem, _ext = os.path.splitext(base)
    stem_lower = stem.lower()
    if is_ai_subtitle(file_path):
        # AI 자막: "🤖 AI " 접두사 + 언어 (아래 규칙으로 언어 판별)
        plain = get_subtitle_label(os.path.join(os.path.dirname(file_path), base.lower().replace(".ai.", ".")))
        language = plain.split(" (")[0].split(" ", 1)[-1] if not plain.startswith("📄") else "자막"
        return f"🤖 AI {language} ({base})"
    
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
    sub_exts = list(SUBTITLE_EXTS)
    
    found_files = []
    seen = set()
    
    # 1. 동일한 파일명 (대소문자 무관)
    for ext in sub_exts:
        for c_ext in [ext, ext.upper()]:
            cand = os.path.join(dir_name, stem + c_ext)
            if os.path.isfile(cand) and cand not in seen:
                seen.add(cand)
                found_files.append(cand)
                
    # 같은 폴더의 영상들 — 자막 파일이 어느 영상의 것인지 판단하는 데 씁니다.
    try:
        dir_files = [f for f in os.listdir(dir_name) if os.path.isfile(os.path.join(dir_name, f))]
    except OSError:
        dir_files = []
    video_stems = {os.path.splitext(f)[0].lower() for f in dir_files if os.path.splitext(f)[1].lower() in VIDEO_EXTS}
    video_stems.add(stem_lower)

    def owner(sub_name_lower):
        """자막 이름에 가장 길게 들어맞는 영상 이름 (없으면 None).
        ep1/ep10처럼 앞부분이 같은 영상이 있어도 더 구체적인 쪽이 자막을 가져갑니다."""
        # 이름이 영상 이름으로 시작하는 경우를 우선합니다. "포함"만 보면 b.ai.ko.srt가 영상 "a"에도 걸립니다.
        matches = [v for v in video_stems if sub_name_lower.startswith(v)]
        if not matches:
            matches = [v for v in video_stems if v in sub_name_lower]
        return max(matches, key=lambda v: (len(v), v)) if matches else None

    subtitle_names = [f for f in dir_files if any(f.lower().endswith(ext) for ext in sub_exts)]

    # 2. 언어 태그가 붙은 자막 (movie.ko.srt 등) — 이 영상이 주인인 것만
    for fname in subtitle_names:
        cand_path = os.path.join(dir_name, fname)
        if cand_path not in seen and owner(fname.lower()) == stem_lower:
            seen.add(cand_path)
            found_files.append(cand_path)

    # 3. 그래도 없으면 어느 영상에도 속하지 않는 자막만 사용 (다른 영상의 자막/AI 자막을 가져오지 않음)
    if not found_files:
        for fname in subtitle_names:
            cand_path = os.path.join(dir_name, fname)
            if cand_path not in seen and owner(fname.lower()) is None:
                seen.add(cand_path)
                found_files.append(cand_path)

    # 영상 폴더에 쓸 수 없어 캐시에 저장된 AI 자막
    for cand_path in find_cached_ai_subtitles(video_path):
        if cand_path not in seen:
            seen.add(cand_path)
            found_files.append(cand_path)

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


_MARKUP_TAG = re.compile(r"<[^>]+>")


def strip_markup(text):
    """Pango/HTML 마크업 태그와 엔티티를 제거한 순수 텍스트 (내장 자막 표시용)"""
    return html.unescape(_MARKUP_TAG.sub("", text)).strip()
