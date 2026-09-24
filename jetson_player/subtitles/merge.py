"""다중 자막 트랙을 언어별 색상 SAMI 파일로 병합"""
import hashlib
import html
import os


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
