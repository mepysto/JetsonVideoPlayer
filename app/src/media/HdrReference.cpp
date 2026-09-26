#include "HdrReference.h"

#include <algorithm>
#include <cmath>

namespace jvp::hdr {

namespace {
// PQ (SMPTE ST 2084)
constexpr double kM1 = 2610.0 / 16384, kM2 = 2523.0 / 4096 * 128;
constexpr double kC1 = 3424.0 / 4096, kC2 = 2413.0 / 4096 * 32, kC3 = 2392.0 / 4096 * 32;
// HLG (ARIB STD-B67)
constexpr double kHa = 0.17883277, kHb = 0.28466892, kHc = 0.55991073;

Mat3 matmul(const Mat3 &a, const Mat3 &b)
{
    Mat3 r{};
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            for (int k = 0; k < 3; ++k)
                r[i][j] += a[i][k] * b[k][j];
    return r;
}

Mat3 inverse(const Mat3 &m)
{
    const double det = m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                       + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
    Mat3 r;
    r[0][0] = (m[1][1] * m[2][2] - m[1][2] * m[2][1]) / det;
    r[0][1] = (m[0][2] * m[2][1] - m[0][1] * m[2][2]) / det;
    r[0][2] = (m[0][1] * m[1][2] - m[0][2] * m[1][1]) / det;
    r[1][0] = (m[1][2] * m[2][0] - m[1][0] * m[2][2]) / det;
    r[1][1] = (m[0][0] * m[2][2] - m[0][2] * m[2][0]) / det;
    r[1][2] = (m[0][2] * m[1][0] - m[0][0] * m[1][2]) / det;
    r[2][0] = (m[1][0] * m[2][1] - m[1][1] * m[2][0]) / det;
    r[2][1] = (m[0][1] * m[2][0] - m[0][0] * m[2][1]) / det;
    r[2][2] = (m[0][0] * m[1][1] - m[0][1] * m[1][0]) / det;
    return r;
}

Mat3 toYcc(double kr, double kb)
{
    const double kg = 1 - kr - kb;
    return {{{kr, kg, kb},
             {-kr / (2 * (1 - kb)), -kg / (2 * (1 - kb)), 0.5},
             {0.5, -kg / (2 * (1 - kr)), -kb / (2 * (1 - kr))}}};
}

double dot(const Vec3 &a, const Vec3 &b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
} // namespace

const Vec3 &luma2020()
{
    static const Vec3 v{0.2627, 0.6780, 0.0593};
    return v;
}

const Mat3 &bt2020To709()
{
    static const Mat3 m{{{1.6605, -0.5876, -0.0728}, {-0.1246, 1.1329, -0.0083}, {-0.0182, -0.1006, 1.1187}}};
    return m;
}

const Mat3 &matrixFix()
{
    static const Mat3 m = matmul(inverse(toYcc(0.2627, 0.0593)), toYcc(0.2126, 0.0722));
    return m;
}

Vec3 mul(const Mat3 &m, const Vec3 &v) { return {dot(m[0], v), dot(m[1], v), dot(m[2], v)}; }

double pqToNits(double e)
{
    e = std::clamp(e, 0.0, 1.0);
    const double p = std::pow(e, 1 / kM2);
    return 10000.0 * std::pow(std::max(p - kC1, 0.0) / (kC2 - kC3 * p), 1 / kM1);
}

Vec3 pqToNits(const Vec3 &e) { return {pqToNits(e[0]), pqToNits(e[1]), pqToNits(e[2])}; }

Vec3 hlgToNits(const Vec3 &rgb)
{
    Vec3 scene;
    for (int i = 0; i < 3; ++i) {
        const double e = std::clamp(rgb[i], 0.0, 1.0);
        scene[i] = e <= 0.5 ? e * e / 3.0 : (std::exp((e - kHc) / kHa) + kHb) / 12.0;
    }
    const double y = dot(scene, luma2020());
    const double gain = kHlgPeakNits * (y > 0 ? std::pow(y, 0.2) : 0.0);
    return {gain * scene[0], gain * scene[1], gain * scene[2]};
}

double tonemap(double x)
{
    return x <= kKnee ? x : kKnee + (1 - kKnee) * (1 - std::exp(-(x - kKnee) / (1 - kKnee)));
}

Vec3 reference(const Vec3 &input, Transfer kind, bool fixMatrix)
{
    Vec3 rgb = fixMatrix ? mul(matrixFix(), input) : input;
    Vec3 lin = kind == Transfer::Pq ? pqToNits(rgb) : hlgToNits(rgb);
    for (double &c : lin)
        c /= kSdrWhiteNits;
    const double y = dot(lin, luma2020());
    if (y > 0) {
        const double s = tonemap(y) / y;
        for (double &c : lin)
            c *= s;
    }
    Vec3 out = mul(bt2020To709(), lin);
    for (double &c : out)
        c = std::pow(std::clamp(c, 0.0, 1.0), 1 / kDisplayGamma);
    return out;
}

} // namespace jvp::hdr
