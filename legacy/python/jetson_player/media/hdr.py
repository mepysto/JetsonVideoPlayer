"""HDR(PQ/HLG) 영상을 SDR 화면에 맞게 톤매핑하는 GL 셰이더 (glshader용)

HDR 영상을 그대로 보이면 PQ/HLG로 부호화된 값이 SDR 감마로 해석되어 색이 바래고 밋밋해 보입니다.
셰이더 순서: (HW 경로) BT.709로 잘못 변환된 RGB를 BT.2020 행렬로 다시 계산 → PQ/HLG를 선형 빛(nit)으로 →
기준 백색 203nit에 맞춰 밝은 부분만 부드럽게 눌러 담는 톤매핑(휘도 기준, 색상 유지) → BT.2020→BT.709 색역 → 감마 2.2.

HW 경로(nvvidconv → NV12)는 caps에 색 정보가 빠져 GL이 BT.709 행렬로 RGB를 만들고,
SW 경로는 caps의 bt2020 정보대로 GL이 올바르게 변환합니다. fix_matrix로 구분합니다.
"""
import numpy as np

SDR_WHITE_NITS = 203.0     # BT.2408: HDR 안의 SDR 기준 백색
KNEE = 0.75                # 이 밝기(SDR 백색 대비)까지는 그대로, 위로는 부드럽게 1.0에 수렴
DISPLAY_GAMMA = 2.2

# PQ (SMPTE ST 2084)
_M1, _M2 = 2610 / 16384, 2523 / 4096 * 128
_C1, _C2, _C3 = 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32
# HLG (ARIB STD-B67)
_HA, _HB, _HC = 0.17883277, 0.28466892, 0.55991073
HLG_PEAK_NITS = 1000.0

_LUMA_2020 = np.array([0.2627, 0.6780, 0.0593])
_BT2020_TO_709 = np.array([[1.6605, -0.5876, -0.0728],
                           [-0.1246, 1.1329, -0.0083],
                           [-0.0182, -0.1006, 1.1187]])


def _ycbcr_matrices(kr, kb):
    kg = 1 - kr - kb
    to_ycc = np.array([[kr, kg, kb],
                       [-kr / (2 * (1 - kb)), -kg / (2 * (1 - kb)), 0.5],
                       [0.5, -kg / (2 * (1 - kr)), -kb / (2 * (1 - kr))]])
    return to_ycc, np.linalg.inv(to_ycc)


_TO_YCC_709, _ = _ycbcr_matrices(0.2126, 0.0722)
_, _FROM_YCC_2020 = _ycbcr_matrices(0.2627, 0.0593)
# BT.709 행렬로 만든 RGB → (Y'CbCr로 되돌려) → BT.2020 행렬로 다시 만든 R'G'B'
MATRIX_FIX = _FROM_YCC_2020 @ _TO_YCC_709


def transfer_of_caps(caps):
    """caps의 colorimetry → "pq" / "hlg" / None

    GStreamer는 colorimetry를 이름(bt2100-pq)이나 숫자(1:6:14:7 — 범위:행렬:전달:원색)로 적으므로
    문자열 비교 대신 VideoColorimetry로 해석해 전달 특성을 봅니다.
    """
    if caps is None or not caps.get_size():
        return None
    text = caps.get_structure(0).get_string("colorimetry")
    if not text:
        return None
    from gi.repository import GstVideo
    colorimetry = GstVideo.VideoColorimetry()
    if not colorimetry.from_string(text):
        return None
    if colorimetry.transfer == GstVideo.VideoTransferFunction.SMPTE2084:
        return "pq"
    if colorimetry.transfer == GstVideo.VideoTransferFunction.ARIB_STD_B67:
        return "hlg"
    return None


# ---- 파이썬 참조 구현 (셰이더와 같은 계산 — 테스트용) -----------------------------------

def pq_to_nits(e):
    e = np.clip(np.asarray(e, dtype=np.float64), 0.0, 1.0)
    p = e ** (1 / _M2)
    return 10000.0 * (np.maximum(p - _C1, 0.0) / (_C2 - _C3 * p)) ** (1 / _M1)


def hlg_to_nits(rgb):
    e = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    scene = np.where(e <= 0.5, e * e / 3.0, (np.exp((e - _HC) / _HA) + _HB) / 12.0)
    y = float(scene @ _LUMA_2020)
    return HLG_PEAK_NITS * (y ** 0.2 if y > 0 else 0.0) * scene      # OOTF (시스템 감마 1.2)


def tonemap(x):
    """SDR 백색 대비 밝기 x → 0~1 (KNEE까지 그대로, 그 위는 1에 수렴)"""
    x = np.asarray(x, dtype=np.float64)
    return np.where(x <= KNEE, x, KNEE + (1 - KNEE) * (1 - np.exp(-(x - KNEE) / (1 - KNEE))))


def reference(rgb, kind, fix_matrix):
    """셰이더와 같은 과정을 파이썬으로: 입력/출력 모두 0~1 R'G'B'"""
    rgb = np.asarray(rgb, dtype=np.float64)
    if fix_matrix:
        rgb = MATRIX_FIX @ rgb
    lin = (pq_to_nits(rgb) if kind == "pq" else hlg_to_nits(rgb)) / SDR_WHITE_NITS
    y = float(lin @ _LUMA_2020)
    if y > 0:
        lin = lin * (float(tonemap(y)) / y)
    out = np.clip(_BT2020_TO_709 @ lin, 0.0, 1.0)
    return out ** (1 / DISPLAY_GAMMA)


# ---- GLSL ------------------------------------------------------------------------------------

def _mat3(m):
    """numpy 행렬 → GLSL mat3 (열 우선)"""
    cols = [f"{m[r][c]:.8f}" for c in range(3) for r in range(3)]
    return "mat3(" + ", ".join(cols) + ")"


# glshader의 기본 정점 셰이더는 #version을 붙이므로, 버전 없는 조각 셰이더와 짝이 맞도록 직접 넘깁니다
# (Mesa 등 일부 GL은 "all shaders must use same shading language version"으로 링크를 거부).
VERTEX_SHADER = """attribute vec4 a_position;
attribute vec2 a_texcoord;
varying vec2 v_texcoord;
void main () {
  gl_Position = a_position;
  v_texcoord = a_texcoord;
}
"""


def uniforms_for(kind, fix_matrix):
    """톤매핑 셰이더에 넘길 uniform 값 (셰이더는 하나, 영상마다 이 값만 바꿉니다)"""
    mode = {"pq": 1.0, "hlg": 2.0}.get(kind, 0.0)
    return {"mode": mode, "fixm": 1.0 if (fix_matrix and mode) else 0.0}


def fragment_shader():
    """PQ/HLG 톤매핑 셰이더. uniform mode: 0 그대로, 1 PQ, 2 HLG / fixm: 1이면 BT.709→BT.2020 행렬 보정 (HW 경로)

    실행 중인 glshader의 소스를 바꾸면 반영되지 않으므로(GStreamer 1.24), 셰이더 하나에 모든 경우를 넣고
    uniforms 속성만 바꿉니다.
    """
    return f"""#ifdef GL_ES
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float mode;
uniform float fixm;
const vec3 LUMA = vec3({_LUMA_2020[0]}, {_LUMA_2020[1]}, {_LUMA_2020[2]});
const mat3 FIX = {_mat3(MATRIX_FIX)};
const mat3 TO709 = {_mat3(_BT2020_TO_709)};
void main () {{
  vec4 src = texture2D(tex, v_texcoord);
  if (mode < 0.5) {{
    gl_FragColor = src;
    return;
  }}
  vec3 e = src.rgb;
  if (fixm > 0.5) {{
    e = FIX * e;
  }}
  e = clamp(e, 0.0, 1.0);
  vec3 nits;
  if (mode < 1.5) {{
    vec3 p = pow(e, vec3({1 / _M2:.10f}));
    nits = 10000.0 * pow(max(p - {_C1:.10f}, 0.0) / ({_C2:.10f} - {_C3:.10f} * p), vec3({1 / _M1:.10f}));
  }} else {{
    vec3 lo = e * e / 3.0;
    vec3 hi = (exp((e - {_HC:.8f}) / {_HA:.8f}) + {_HB:.8f}) / 12.0;
    vec3 scene = mix(lo, hi, step(0.5, e));
    float ys = max(dot(scene, LUMA), 1e-6);
    nits = {HLG_PEAK_NITS:.1f} * pow(ys, 0.2) * scene;
  }}
  vec3 lin = nits / {SDR_WHITE_NITS:.1f};
  float y = dot(lin, LUMA);
  float t = y <= {KNEE} ? y : {KNEE} + {1 - KNEE} * (1.0 - exp(-(y - {KNEE}) / {1 - KNEE}));
  lin = y > 0.0 ? lin * (t / y) : lin;
  vec3 outc = clamp(TO709 * lin, 0.0, 1.0);
  gl_FragColor = vec4(pow(outc, vec3({1 / DISPLAY_GAMMA:.6f})), src.a);
}}
"""
