import numpy as np
import pytest

from jetson_player.media import hdr


def test_pq_reference_points():
    assert hdr.pq_to_nits(0.0) == pytest.approx(0.0)
    assert hdr.pq_to_nits(1.0) == pytest.approx(10000.0, rel=1e-6)
    assert hdr.pq_to_nits(0.5080784) == pytest.approx(100.0, rel=1e-3)     # PQ 100nit


def test_tonemap_keeps_midtones_and_compresses_highlights():
    assert hdr.tonemap(0.5) == pytest.approx(0.5)
    assert hdr.tonemap(1.0) < 1.0 and hdr.tonemap(10.0) == pytest.approx(1.0, abs=1e-6)
    x = np.linspace(0, 20, 200)
    assert np.all(np.diff(hdr.tonemap(x)) >= 0)                          # 단조 증가


def test_sdr_white_in_hdr_maps_near_display_white():
    """HDR 안의 SDR 기준 백색(203nit, PQ≈0.58)은 SDR 화면에서 거의 흰색이어야 합니다."""
    m1, m2, c1, c2, c3 = 2610 / 16384, 2523 / 4096 * 128, 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32
    y = (203 / 10000) ** m1
    pq = ((c1 + c2 * y) / (1 + c3 * y)) ** m2
    out = hdr.reference(np.array([pq, pq, pq]), "pq", fix_matrix=False)
    assert np.all(out > 0.9)


def test_matrix_fix_is_identity_for_grays():
    gray = np.array([0.4, 0.4, 0.4])
    assert hdr.MATRIX_FIX @ gray == pytest.approx(gray, abs=1e-9)


def test_uniforms_and_shader_source():
    assert hdr.uniforms_for(None, True) == {"mode": 0.0, "fixm": 0.0}
    assert hdr.uniforms_for("pq", True) == {"mode": 1.0, "fixm": 1.0}
    assert hdr.uniforms_for("hlg", False) == {"mode": 2.0, "fixm": 0.0}
    src = hdr.fragment_shader()
    assert "uniform float mode" in src and "uniform float fixm" in src and src.count("{") == src.count("}")


def test_transfer_of_caps():
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    cap = lambda c: Gst.Caps.from_string(f"video/x-raw,colorimetry={c}")  # noqa: E731
    assert hdr.transfer_of_caps(cap("bt2100-pq")) == "pq"
    assert hdr.transfer_of_caps(cap("bt2100-hlg")) == "hlg"
    assert hdr.transfer_of_caps(cap("bt709")) is None
    # 전체 범위 등 이름 있는 조합이 아니면 숫자로 적힘 (범위:행렬:전달:원색)
    assert hdr.transfer_of_caps(cap("1:6:14:7")) == "pq"
    assert hdr.transfer_of_caps(cap("1:6:15:7")) == "hlg"
    assert hdr.transfer_of_caps(cap("2:4:5:2")) is None
    assert hdr.transfer_of_caps(Gst.Caps.from_string("video/x-raw")) is None and hdr.transfer_of_caps(None) is None
