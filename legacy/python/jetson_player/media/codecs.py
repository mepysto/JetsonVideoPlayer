"""Jetson Orin NVDEC(nvv4l2decoder)가 디코딩할 수 있는 영상 형식 판별.

재생 전에 판별해 두면, 하드웨어 디코더가 첫 프레임에서 실패한 뒤 소프트웨어 경로로
다시 시작하는 끊김 없이 처음부터 알맞은 경로를 고를 수 있습니다.
"""
import re

# 코덱별 NVDEC 지원 범위 (4:2:0 샘플링만 지원, 최대 비트 깊이)
NVDEC_MAX_BITS = {
    "h264": 8,
    "hevc": 12,
    "vp9": 12,
    "av1": 10,
}
CODEC_ALIASES = {"avc": "h264", "avc1": "h264", "h265": "hevc", "hvc1": "hevc", "hev1": "hevc", "av01": "av1"}


def chroma_and_depth(pix_fmt):
    """ffprobe pix_fmt → (샘플링 '420'/'422'/'444'/None, 비트 깊이)"""
    fmt = (pix_fmt or "").lower()
    if fmt.startswith(("p010", "p016")):
        depth = int(fmt[1:4])
    else:
        depth_match = re.search(r"p(\d{2})", fmt) or re.search(r"(\d{2})(?:le|be)$", fmt)
        depth = int(depth_match.group(1)) if depth_match else 8
    if fmt.startswith(("nv12", "yuvj420", "yuv420")) or fmt.startswith("p010") or fmt.startswith("p016"):
        chroma = "420"
    elif fmt.startswith(("yuv422", "yuvj422", "nv16")):
        chroma = "422"
    elif fmt.startswith(("yuv444", "yuvj444", "gbr", "rgb", "bgr")):
        chroma = "444"
    else:
        chroma = None
    return chroma, depth


def nvdec_supports(codec, pix_fmt, profile=""):
    """(지원 여부, 사유). 형식 정보가 부족하면 코덱만으로 판단합니다."""
    codec = CODEC_ALIASES.get((codec or "").lower(), (codec or "").lower())
    max_bits = NVDEC_MAX_BITS.get(codec)
    if max_bits is None:
        return False, f"NVDEC 미지원 코덱 ({codec.upper() or '알 수 없음'})"
    chroma, depth = chroma_and_depth(pix_fmt)
    profile_l = (profile or "").lower()
    if chroma is None:
        # pix_fmt를 모르면 프로파일 이름으로 4:4:4/4:2:2 여부만 확인
        if any(k in profile_l for k in ("4:4:4", "444", "4:2:2", "422", "profile 1", "profile 3", "rext")):
            return False, f"{codec.upper()} {profile} (4:2:0 아님)"
        return True, f"{codec.upper()} NVDEC 지원 (형식 정보 부족)"
    if chroma != "420":
        return False, f"{codec.upper()} {chroma[0]}:{chroma[1]}:{chroma[2]} 샘플링은 NVDEC 미지원"
    if depth > max_bits:
        return False, f"{codec.upper()} {depth}-bit는 NVDEC 미지원 (최대 {max_bits}-bit)"
    return True, f"{codec.upper()} {depth}-bit 4:2:0 NVDEC 지원"
