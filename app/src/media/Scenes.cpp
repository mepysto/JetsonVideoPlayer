#include "Scenes.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace jvp::scenes {

namespace {
// numpy.linspace(0, n, k+1, dtype=int)과 같은 경계
std::vector<int> edges(int n, int k)
{
    std::vector<int> e(k + 1);
    const double step = double(n) / k;
    for (int i = 0; i < k; ++i)
        e[i] = int(i * step);
    e[k] = n;
    return e;
}

// numpy.median (짝수 개면 가운데 두 값의 평균)
double median(std::vector<float> v)
{
    if (v.empty())
        return 0.0;
    std::sort(v.begin(), v.end());
    const size_t n = v.size();
    return n % 2 ? v[n / 2] : (double(v[n / 2 - 1]) + v[n / 2]) / 2.0;
}
} // namespace

Signature imageSignature(const uchar *rgba, int width, int height)
{
    Signature sig(kSignatureLen, 0.f);
    const auto ys = edges(height, kSignatureH), xs = edges(width, kSignatureW);
    for (int j = 0; j < kSignatureH; ++j) {
        for (int i = 0; i < kSignatureW; ++i) {
            double sum[3] = {0, 0, 0};
            const int count = (ys[j + 1] - ys[j]) * (xs[i + 1] - xs[i]);
            for (int y = ys[j]; y < ys[j + 1]; ++y) {
                const uchar *row = rgba + size_t(y) * width * 4;
                for (int x = xs[i]; x < xs[i + 1]; ++x)
                    for (int c = 0; c < 3; ++c)
                        sum[c] += row[x * 4 + c];
            }
            for (int c = 0; c < 3; ++c)
                sig[(j * kSignatureW + i) * 3 + c] = count ? float(sum[c] / count) : NAN;
        }
    }
    return sig;
}

QList<qint64> detectSceneChanges(const std::vector<Signature> &signatures, const QList<qint64> &positions,
                                 qint64 duration, double sensitivity, double minGapRatio, int maxScenes)
{
    if (signatures.size() < 3 || duration <= 0)
        return {};
    std::vector<float> diffs;   // 경계 i: positions[i] → positions[i+1]
    for (size_t k = 1; k < signatures.size(); ++k) {
        const auto &a = signatures[k - 1], &b = signatures[k];
        const size_t n = std::min(a.size(), b.size());
        double s = 0;
        for (size_t i = 0; i < n; ++i)
            s += std::abs(double(b[i]) - a[i]);
        diffs.push_back(n ? float(s / n) : 0.f);
    }
    return sceneChangesFromDiffs(diffs, positions.mid(1), duration, sensitivity, duration * minGapRatio, maxScenes);
}

QList<qint64> sceneChangesFromDiffs(const std::vector<float> &diffs, const QList<qint64> &positions, qint64 duration,
                                    double sensitivity, double minGapNs, int maxScenes)
{
    if (diffs.size() < 2 || duration <= 0)
        return {};
    // 장면 전환 값 자체가 평균/표준편차를 부풀리지 않도록 중앙값과 MAD(중앙값 절대 편차)로 기준을 잡습니다.
    const double med = median(diffs);
    std::vector<float> dev(diffs.size());
    for (size_t i = 0; i < diffs.size(); ++i)
        dev[i] = float(std::abs(diffs[i] - med));
    const double mad = median(dev) * 1.4826;
    const double threshold = std::max(12.0, med + sensitivity * std::max(mad, 1.0));

    std::vector<size_t> order(diffs.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](size_t a, size_t b) { return diffs[a] > diffs[b]; });

    QList<qint64> chosen;
    for (size_t i : order) {
        if (diffs[i] < threshold)
            break;   // 내림차순이므로 나머지는 모두 기준 미만
        if (qsizetype(i) >= positions.size())
            continue;
        const qint64 pos = positions[qsizetype(i)];
        if (pos <= minGapNs || pos >= duration - minGapNs)
            continue;
        if (std::all_of(chosen.begin(), chosen.end(), [&](qint64 c) { return std::llabs(pos - c) >= minGapNs; }))
            chosen.append(pos);
        if (chosen.size() >= maxScenes)
            break;
    }
    std::sort(chosen.begin(), chosen.end());
    return chosen;
}

} // namespace jvp::scenes
