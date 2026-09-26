#include "Codecs.h"

#include <QHash>
#include <QRegularExpression>
#include <QStringList>
#include <initializer_list>

namespace jvp::codecs {

namespace {
// NVDEC는 4:2:0 샘플링만 지원하고, 코덱마다 최대 비트 깊이가 다릅니다
const QHash<QString, int> &maxBits()
{
    static const QHash<QString, int> m = {{"h264", 8}, {"hevc", 12}, {"vp9", 12}, {"av1", 10}};
    return m;
}

const QHash<QString, QString> &aliases()
{
    static const QHash<QString, QString> m = {{"avc", "h264"},  {"avc1", "h264"}, {"h265", "hevc"},
                                              {"hvc1", "hevc"}, {"hev1", "hevc"}, {"av01", "av1"}};
    return m;
}

bool startsWithAny(const QString &s, std::initializer_list<const char *> prefixes)
{
    for (const char *p : prefixes)
        if (s.startsWith(QLatin1String(p)))
            return true;
    return false;
}
} // namespace

ChromaDepth chromaAndDepth(const QString &pixFmt)
{
    const QString fmt = pixFmt.toLower();
    ChromaDepth r;
    if (startsWithAny(fmt, {"p010", "p016"})) {
        r.depth = fmt.mid(1, 3).toInt();
    } else {
        static const QRegularExpression pDigits(QStringLiteral("p(\\d{2})"));
        static const QRegularExpression endDigits(QStringLiteral("(\\d{2})(?:le|be)$"));
        QRegularExpressionMatch m = pDigits.match(fmt);
        if (!m.hasMatch())
            m = endDigits.match(fmt);
        r.depth = m.hasMatch() ? m.captured(1).toInt() : 8;
    }
    if (startsWithAny(fmt, {"nv12", "yuvj420", "yuv420", "p010", "p016"}))
        r.chroma = QStringLiteral("420");
    else if (startsWithAny(fmt, {"yuv422", "yuvj422", "nv16"}))
        r.chroma = QStringLiteral("422");
    else if (startsWithAny(fmt, {"yuv444", "yuvj444", "gbr", "rgb", "bgr"}))
        r.chroma = QStringLiteral("444");
    return r;
}

QString canonicalCodec(const QString &codec)
{
    const QString c = codec.toLower();
    return aliases().value(c, c);
}

int nvdecMaxBits(const QString &codec) { return maxBits().value(canonicalCodec(codec), 0); }

NvdecDecision nvdecSupports(const QString &codecIn, const QString &pixFmt, const QString &profile)
{
    const QString codec = canonicalCodec(codecIn);
    const QString up = codec.toUpper();
    const int max = maxBits().value(codec, 0);
    if (max == 0)
        return {false, QStringLiteral("NVDEC 미지원 코덱 (%1)").arg(up.isEmpty() ? QStringLiteral("알 수 없음") : up)};
    const ChromaDepth cd = chromaAndDepth(pixFmt);
    const QString profileL = profile.toLower();
    if (cd.chroma.isNull()) {
        // pix_fmt를 모르면 프로파일 이름으로 4:4:4/4:2:2 여부만 확인
        for (const char *k : {"4:4:4", "444", "4:2:2", "422", "profile 1", "profile 3", "rext"})
            if (profileL.contains(QLatin1String(k)))
                return {false, QStringLiteral("%1 %2 (4:2:0 아님)").arg(up, profile)};
        return {true, QStringLiteral("%1 NVDEC 지원 (형식 정보 부족)").arg(up)};
    }
    if (cd.chroma != QLatin1String("420")) {
        const QString ratio = QStringList{cd.chroma.mid(0, 1), cd.chroma.mid(1, 1), cd.chroma.mid(2, 1)}.join(QLatin1Char(':'));
        return {false, QStringLiteral("%1 %2 샘플링은 NVDEC 미지원").arg(up, ratio)};
    }
    if (cd.depth > max)
        return {false, QStringLiteral("%1 %2-bit는 NVDEC 미지원 (최대 %3-bit)").arg(up).arg(cd.depth).arg(max)};
    return {true, QStringLiteral("%1 %2-bit 4:2:0 NVDEC 지원").arg(up).arg(cd.depth)};
}

} // namespace jvp::codecs
