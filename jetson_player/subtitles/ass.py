"""ASS/SSA 자막의 스타일·위치 해석 (GTK 비의존)

지원: [V4+ Styles]/[V4 Styles] 스타일(글꼴·크기·색·굵게/기울임/밑줄·외곽선·그림자·정렬·여백·불투명 상자),
재정의 태그 \\b \\i \\u \\s \\fn \\fs \\c \\1c \\3c \\4c \\alpha \\1a \\3a \\bord \\shad \\an \\a \\pos \\move(시작 위치)
\\r \\N \\n \\h, 그리기 모드(\\p1)는 건너뜀. 애니메이션(\\t, \\fad, \\k 등)은 무시하고 정적인 모양으로 그립니다.

화면에 그리는 일은 ui/subtitle_overlay.py가 맡고, 여기서는 "어디에 무엇을 어떤 모양으로"만 계산합니다.
"""
import bisect
import re
import threading
from dataclasses import dataclass, field, replace

DEFAULT_PLAY_RES = (384, 288)   # ASS 명세의 기본값 (PlayResX/Y가 없을 때)


@dataclass(frozen=True)
class AssStyle:
    name: str = "Default"
    font: str = "Sans"
    size: float = 20.0
    primary: tuple = (1.0, 1.0, 1.0, 1.0)      # (r, g, b, a) — a=1 불투명
    outline_color: tuple = (0.0, 0.0, 0.0, 1.0)
    back_color: tuple = (0.0, 0.0, 0.0, 0.5)
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikeout: bool = False
    border_style: int = 1                     # 1: 외곽선+그림자, 3: 불투명 상자
    outline: float = 2.0
    shadow: float = 0.0
    alignment: int = 2                        # 키패드 방식 (1~9, 2 = 아래 가운데)
    margin_l: int = 10
    margin_r: int = 10
    margin_v: int = 10


@dataclass(frozen=True)
class AssRun:
    """한 이벤트 안에서 모양이 같은 글자 묶음"""
    text: str
    font: str
    size: float
    color: tuple
    bold: bool
    italic: bool
    underline: bool
    strikeout: bool


@dataclass
class AssEvent:
    start: int
    end: int
    layer: int
    style: AssStyle
    runs: list                                  # [AssRun] ("\n"은 줄바꿈)
    alignment: int
    margin_l: int
    margin_r: int
    margin_v: int
    pos: tuple = None                           # \pos 기준점 (PlayRes 좌표) 또는 None
    outline: float = 2.0
    shadow: float = 0.0
    outline_color: tuple = (0.0, 0.0, 0.0, 1.0)
    back_color: tuple = (0.0, 0.0, 0.0, 0.5)
    order: int = 0                              # 파일 안 순서 (같은 레이어에서 겹칠 때)
    alignment_locked: bool = False              # 첫 \an/\a만 적용 (명세)

    @property
    def plain_text(self):
        return "".join(r.text for r in self.runs).strip()


@dataclass
class AssScript:
    play_res: tuple = DEFAULT_PLAY_RES
    styles: dict = field(default_factory=dict)
    events: list = field(default_factory=list)   # 시작 순 정렬
    _starts: list = field(default_factory=list, repr=False)
    _max_duration: int = 0
    _lock: object = field(default_factory=threading.Lock, repr=False, compare=False)

    def finalize(self):
        with self._lock:
            self.events.sort(key=lambda e: (e.start, e.order))
            self._starts = [e.start for e in self.events]
            self._max_duration = max((e.end - e.start for e in self.events), default=0)
        return self

    def add_events(self, events):
        """재생 중에 도착하는 대사 추가 (MKV 내장 ASS — 스트리밍 스레드에서 호출).
        탐색하면 같은 블록이 다시 오므로 (순서 번호, 시작 시각)이 같은 대사는 건너뜁니다."""
        with self._lock:
            known = {(e.order, e.start) for e in self.events}
            new = [e for e in events if (e.order, e.start) not in known]
            if not new:
                return self
            self.events.extend(new)
        return self.finalize()

    def active_at(self, t_ms):
        """t_ms에 보이는 이벤트 (레이어 → 파일 순서대로, 아래 레이어 먼저 그림)"""
        found = []
        with self._lock:
            i = bisect.bisect_right(self._starts, t_ms) - 1
            while i >= 0 and self._starts[i] >= t_ms - self._max_duration:
                ev = self.events[i]
                if ev.start <= t_ms < ev.end and ev.plain_text:
                    found.append(ev)
                i -= 1
        found.sort(key=lambda e: (e.layer, e.order))
        return found


# ---- 기본 값 해석 ------------------------------------------------------------

def parse_color(value, default=(1.0, 1.0, 1.0, 1.0)):
    """&HAABBGGRR / &HBBGGRR / 10진수 → (r, g, b, a). ASS 알파는 00이 불투명입니다."""
    if value is None:
        return default
    v = str(value).strip().rstrip("&").strip()
    try:
        if v.upper().startswith("&H"):
            n = int(v[2:], 16)
        elif v.upper().startswith("H"):
            n = int(v[1:], 16)
        else:
            n = int(v)
    except ValueError:
        return default
    n &= 0xFFFFFFFF
    alpha = (n >> 24) & 0xFF
    b, g, r = (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF
    return (r / 255.0, g / 255.0, b / 255.0, 1.0 - alpha / 255.0)


def parse_alpha(value):
    """&HAA& → 불투명도 (0~1)"""
    try:
        n = int(str(value).strip().strip("&").upper().lstrip("H") or "0", 16) & 0xFF
    except ValueError:
        return None
    return 1.0 - n / 255.0


def legacy_alignment(a):
    """SSA(V4) \\a 정렬값 → 키패드 정렬값 (1~3 아래, +4 위, +8 가운데)"""
    base = a & 3 or 2
    if a & 4:
        return base + 6
    if a & 8:
        return base + 3
    return base


def ass_time_to_ms(value):
    m = re.match(r"\s*(\d+):(\d+):(\d+)[.:](\d+)", value)
    if not m:
        return 0
    h, mi, s, frac = m.groups()
    frac_ms = int(frac.ljust(3, "0")[:3]) if len(frac) != 2 else int(frac) * 10
    return ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1000 + frac_ms


def _flag(value):
    try:
        return int(float(value)) != 0
    except (TypeError, ValueError):
        return False


def _num(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_style(fields, values, legacy):
    row = dict(zip(fields, (v.strip() for v in values)))
    d = AssStyle()
    align = int(_num(row.get("alignment"), 2))
    return AssStyle(
        name=row.get("name", d.name),
        font=row.get("fontname") or d.font,
        size=_num(row.get("fontsize"), d.size),
        primary=parse_color(row.get("primarycolour"), d.primary),
        outline_color=parse_color(row.get("outlinecolour") or row.get("tertiarycolour"), d.outline_color),
        back_color=parse_color(row.get("backcolour"), d.back_color),
        bold=_flag(row.get("bold")),
        italic=_flag(row.get("italic")),
        underline=_flag(row.get("underline")),
        strikeout=_flag(row.get("strikeout")),
        border_style=int(_num(row.get("borderstyle"), 1)),
        outline=_num(row.get("outline"), d.outline),
        shadow=_num(row.get("shadow"), d.shadow),
        alignment=legacy_alignment(align) if legacy else (align if 1 <= align <= 9 else 2),
        margin_l=int(_num(row.get("marginl"), d.margin_l)),
        margin_r=int(_num(row.get("marginr"), d.margin_r)),
        margin_v=int(_num(row.get("marginv"), d.margin_v)),
    )


# ---- 재정의 태그 ---------------------------------------------------------------

_BLOCK = re.compile(r"\{([^}]*)\}")
# 태그 이름 뒤에 글자가 바로 붙는 경우(\fnComic Sans, \rSign)가 있어 알려진 태그 이름을 긴 것부터 맞춥니다.
_TAG_NAMES = sorted("""1c 2c 3c 4c 1a 2a 3a 4a alpha xbord ybord bord xshad yshad shad blur be fscx fscy fsp fs fn fe
    frx fry frz fr fax fay an a pos move org fade fad iclip clip kf ko k K q r b i u s p t c""".split(),
                    key=len, reverse=True)
_TAG = re.compile(r"\\(" + "|".join(_TAG_NAMES) + r")(\([^)]*\)|[^\\]*)")


def _parse_text(text, style, styles, event):
    """대사 텍스트의 재정의 태그를 해석해 event의 runs/정렬/위치/외곽선을 채웁니다."""
    state = {"font": style.font, "size": style.size, "color": style.primary, "bold": style.bold,
             "italic": style.italic, "underline": style.underline, "strikeout": style.strikeout}
    runs = []
    drawing = False
    pos = 0
    for m in list(_BLOCK.finditer(text)) + [None]:
        chunk = text[pos:m.start()] if m else text[pos:]
        if chunk and not drawing:
            chunk = chunk.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", "\u00a0")
            runs.append(AssRun(chunk, **state))
        if m is None:
            break
        pos = m.end()
        for name, arg in _TAG.findall(m.group(1)):
            arg = arg.strip()
            args = [a.strip() for a in arg.strip("()").split(",")] if arg.startswith("(") else [arg]
            lname = name.lower()
            if lname == "b":
                state["bold"] = _num(args[0], 0) not in (0, 400) if args[0] else style.bold
            elif lname == "i":
                state["italic"] = _flag(args[0]) if args[0] else style.italic
            elif lname == "u":
                state["underline"] = _flag(args[0]) if args[0] else style.underline
            elif lname == "s":
                state["strikeout"] = _flag(args[0]) if args[0] else style.strikeout
            elif lname == "fn":
                state["font"] = args[0] or style.font
            elif lname == "fs" and args[0]:
                state["size"] = _num(args[0], state["size"])
            elif lname in ("c", "1c"):
                c = parse_color(args[0], None) if args[0] else style.primary
                if c:
                    state["color"] = c[:3] + (state["color"][3],)
            elif lname == "3c":
                c = parse_color(args[0], None) if args[0] else style.outline_color
                if c:
                    event.outline_color = c[:3] + (event.outline_color[3],)
            elif lname == "4c":
                c = parse_color(args[0], None) if args[0] else style.back_color
                if c:
                    event.back_color = c[:3] + (event.back_color[3],)
            elif lname in ("alpha", "1a", "3a"):
                a = parse_alpha(args[0])
                if a is not None:
                    if lname in ("alpha", "1a"):
                        state["color"] = state["color"][:3] + (a,)
                    if lname in ("alpha", "3a"):
                        event.outline_color = event.outline_color[:3] + (a,)
            elif lname == "bord" and args[0]:
                event.outline = _num(args[0], event.outline)
            elif lname == "shad" and args[0]:
                event.shadow = _num(args[0], event.shadow)
            elif lname == "an" and args[0]:
                n = int(_num(args[0], 0))
                if 1 <= n <= 9 and not event.alignment_locked:
                    event.alignment, event.alignment_locked = n, True
            elif lname == "a" and args[0]:
                n = int(_num(args[0], 0))
                if n and not event.alignment_locked:
                    event.alignment, event.alignment_locked = legacy_alignment(n), True
            elif lname in ("pos", "move") and len(args) >= 2 and event.pos is None:
                event.pos = (_num(args[0], 0), _num(args[1], 0))
            elif lname == "r":
                base = styles.get(args[0], style) if args[0] else style
                state = {"font": base.font, "size": base.size, "color": base.primary, "bold": base.bold,
                         "italic": base.italic, "underline": base.underline, "strikeout": base.strikeout}
            elif lname == "p" and args[0]:
                drawing = _num(args[0], 0) > 0
    event.runs = [r for r in runs if r.text]


# ---- 파일 해석 ---------------------------------------------------------------

def parse_ass(content):
    """ASS/SSA 텍스트 → AssScript"""
    script = AssScript()
    section = ""
    style_fields = None
    event_fields = None
    legacy = False
    res_x = res_y = None
    order = 0
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            legacy = section == "v4 styles"
            continue
        key, _, value = line.partition(":")
        key_l = key.strip().lower()
        if section == "script info":
            if key_l == "playresx":
                res_x = int(_num(value, 0)) or None
            elif key_l == "playresy":
                res_y = int(_num(value, 0)) or None
        elif section in ("v4+ styles", "v4 styles"):
            if key_l == "format":
                style_fields = [f.strip().lower() for f in value.split(",")]
            elif key_l == "style" and style_fields:
                style = _parse_style(style_fields, value.split(",", len(style_fields) - 1), legacy)
                script.styles[style.name] = style
        elif section == "events":
            if key_l == "format":
                event_fields = [f.strip().lower() for f in value.split(",")]
            elif key_l == "dialogue":
                fields = event_fields or ["layer", "start", "end", "style", "name", "marginl", "marginr",
                                          "marginv", "effect", "text"]
                ev = dialogue_to_event(dict(zip(fields, value.split(",", len(fields) - 1))), script.styles, order)
                if ev is not None:
                    script.events.append(ev)
                    order += 1
    # PlayRes가 하나만 있으면 4:3 기준으로 나머지를 맞춥니다 (libass와 같은 규칙).
    if res_x and not res_y:
        res_y = 1024 if res_x == 1280 else max(1, res_x * 3 // 4)
    if res_y and not res_x:
        res_x = 1280 if res_y == 1024 else max(1, res_y * 4 // 3)
    script.play_res = (res_x or DEFAULT_PLAY_RES[0], res_y or DEFAULT_PLAY_RES[1])
    return script.finalize()


MATROSKA_FIELDS = ("readorder", "layer", "style", "name", "marginl", "marginr", "marginv", "effect", "text")


def matroska_block_to_event(payload, styles, start_ms, end_ms):
    """MKV 내장 ASS 블록 (ReadOrder,Layer,Style,Name,MarginL,MarginR,MarginV,Effect,Text) → AssEvent"""
    row = dict(zip(MATROSKA_FIELDS, payload.split(",", len(MATROSKA_FIELDS) - 1)))
    order = int(_num(row.get("readorder"), 0))
    return dialogue_to_event(row, styles, order, start_ms=start_ms, end_ms=end_ms)


def dialogue_to_event(row, styles, order=0, start_ms=None, end_ms=None):
    """Dialogue 필드 dict → AssEvent (끝 ≤ 시작이거나 텍스트가 없으면 None)"""
    start = start_ms if start_ms is not None else ass_time_to_ms(row.get("start", ""))
    end = end_ms if end_ms is not None else ass_time_to_ms(row.get("end", ""))
    if end <= start:
        return None
    style_name = (row.get("style") or "Default").strip().lstrip("*")
    style = styles.get(style_name) or styles.get("Default") or AssStyle()

    def margin(key, default):
        v = int(_num(row.get(key), 0))
        return v if v else default

    ev = AssEvent(start=start, end=end, layer=int(_num(row.get("layer"), 0)),
                  style=style, runs=[], alignment=style.alignment,
                  margin_l=margin("marginl", style.margin_l), margin_r=margin("marginr", style.margin_r),
                  margin_v=margin("marginv", style.margin_v), outline=style.outline, shadow=style.shadow,
                  outline_color=style.outline_color, back_color=style.back_color, order=order)
    _parse_text(row.get("text", ""), style, styles, ev)
    return ev if ev.plain_text else None


def events_as_plain(script):
    """[(start_ms, end_ms, text)] — 검색·번역·리모컨 등 텍스트만 쓰는 곳용"""
    return [(e.start, e.end, e.plain_text) for e in script.events]


# ---- 화면 배치 ---------------------------------------------------------------

def anchor_point(event, play_res):
    """정렬·여백·\\pos로 정한 기준점 (PlayRes 좌표)과 가로/세로 정렬 (0 왼쪽/위, 0.5 가운데, 1 오른쪽/아래)"""
    col = (event.alignment - 1) % 3          # 0 왼쪽, 1 가운데, 2 오른쪽
    row = (event.alignment - 1) // 3         # 0 아래, 1 가운데, 2 위
    h_align = (0.0, 0.5, 1.0)[col]
    v_align = (1.0, 0.5, 0.0)[row]
    if event.pos is not None:
        return event.pos[0], event.pos[1], h_align, v_align
    px, py = play_res
    x = (event.margin_l, (event.margin_l + px - event.margin_r) / 2, px - event.margin_r)[col]
    y = (py - event.margin_v, py / 2, event.margin_v)[row]
    return x, y, h_align, v_align


def scaled_run(run, factor):
    return replace(run, size=run.size * factor)
