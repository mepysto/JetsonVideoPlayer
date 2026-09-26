#include "SubtitleParse.h"

#include "Paths.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <QLoggingCategory>
#include <QRegularExpression>
#include <QSet>
#include <QStringDecoder>
#include <algorithm>

#include <glib.h>

Q_LOGGING_CATEGORY(lcSubParse, "jvp.subtitles")

namespace jvp::subtitles {

const QStringList kSubtitleExts = {QStringLiteral(".srt"), QStringLiteral(".smi"), QStringLiteral(".vtt"),
                                   QStringLiteral(".ass"), QStringLiteral(".ssa"), QStringLiteral(".sub")};
const QStringList kVideoExts = {QStringLiteral(".webm"), QStringLiteral(".mp4"), QStringLiteral(".mkv"),
                                QStringLiteral(".mov"),  QStringLiteral(".avi"), QStringLiteral(".ts"),
                                QStringLiteral(".m4v")};
const QString kAiSubtitleColor = QStringLiteral("#B388FF");
const QStringList kFallbackPalette = {QStringLiteral("#B388FF"), QStringLiteral("#80CBC4"),
                                      QStringLiteral("#FFF59D"), QStringLiteral("#FFAB91"),
                                      QStringLiteral("#CE93D8"), QStringLiteral("#80DEEA")};

QString languageColor(const QString &code)
{
    static const QHash<QString, QString> colors = {
        {QStringLiteral("ko"), QStringLiteral("#FFFFFF")}, // 한국어: 화이트 (메인 기본)
        {QStringLiteral("en"), QStringLiteral("#FFE066")}, // 영어: 레몬 옐로우
        {QStringLiteral("zh"), QStringLiteral("#64D2FF")}, // 중국어: 스카이블루
        {QStringLiteral("ja"), QStringLiteral("#69F0AE")}, // 일본어: 네온 민트
        {QStringLiteral("es"), QStringLiteral("#FF80AB")}, // 스페인어: 소프트 핑크
        {QStringLiteral("fr"), QStringLiteral("#FFB74D")}, // 프랑스어: 앰버 오렌지
        {QStringLiteral("de"), QStringLiteral("#D1C4E9")}, // 독일어: 소프트 라벤더
        {QStringLiteral("ru"), QStringLiteral("#FF8A80")}, // 러시아어: 코랄 레드
    };
    return colors.value(code);
}

namespace {

// 파이썬 str.splitlines()와 같은 줄 구분 (\r\n은 한 번)
QStringList splitLines(const QString &s)
{
    static const QRegularExpression re(QStringLiteral("\r\n|[\n\r\v\f\x1c\x1d\x1e\u0085\u2028\u2029]"));
    QStringList parts = s.split(re);
    if (!parts.isEmpty() && parts.last().isEmpty())
        parts.removeLast(); // 끝의 줄바꿈은 빈 줄을 만들지 않음
    return parts;
}

// 파이썬 str.split(sep, maxsplit)
QStringList splitMax(const QString &s, QChar sep, int maxSplit)
{
    QStringList out;
    int from = 0;
    while (maxSplit-- > 0) {
        const int i = s.indexOf(sep, from);
        if (i < 0)
            break;
        out << s.mid(from, i - from);
        from = i + 1;
    }
    out << s.mid(from);
    return out;
}

// os.path.splitext(basename)[0] — 맨 앞의 점(숨김 파일)은 확장자로 보지 않습니다.
QString stemOf(const QString &base)
{
    const int dot = base.lastIndexOf(QLatin1Char('.'));
    if (dot <= 0)
        return base;
    for (int i = 0; i < dot; ++i)
        if (base.at(i) != QLatin1Char('.'))
            return base.left(dot);
    return base;
}

QString extOf(const QString &base) { return base.mid(stemOf(base).size()); }

QString baseName(const QString &path)
{
    const int slash = path.lastIndexOf(QLatin1Char('/'));
    return slash < 0 ? path : path.mid(slash + 1);
}

QString absPath(const QString &path) { return QDir::cleanPath(QFileInfo(path).absoluteFilePath()); }

QString dirOf(const QString &absFile)
{
    const int slash = absFile.lastIndexOf(QLatin1Char('/'));
    return slash <= 0 ? QStringLiteral("/") : absFile.left(slash);
}

QString joinPath(const QString &dir, const QString &name)
{
    return dir.endsWith(QLatin1Char('/')) ? dir + name : dir + QLatin1Char('/') + name;
}

bool containsAny(const QString &hay, std::initializer_list<const char *> keys)
{
    for (const char *k : keys)
        if (hay.contains(QString::fromUtf8(k)))
            return true;
    return false;
}

// 파이썬 float() 흉내 (실패 시 기본값)
double num(const QString &v, double def)
{
    bool ok = false;
    const double d = v.trimmed().toDouble(&ok);
    return ok ? d : def;
}

// 파이썬 int() 흉내 (앞뒤 공백·부호 허용)
bool toInt(const QString &v, qint64 *out)
{
    bool ok = false;
    *out = v.trimmed().toLongLong(&ok);
    return ok;
}

bool gConvertStrict(const QByteArray &raw, const char *from, QString *out)
{
    gsize read = 0, written = 0;
    GError *err = nullptr;
    gchar *conv = g_convert(raw.constData(), raw.size(), "UTF-8", from, &read, &written, &err);
    if (err || !conv || read != gsize(raw.size())) {
        if (err)
            g_error_free(err);
        g_free(conv);
        return false;
    }
    *out = QString::fromUtf8(conv, qsizetype(written));
    g_free(conv);
    return true;
}

// 파이썬 html.unescape의 흔한 부분 (숫자 참조 + 자주 쓰는 이름)
QString htmlUnescape(const QString &s)
{
    if (!s.contains(QLatin1Char('&')))
        return s;
    static const QHash<QString, QString> named = {
        {QStringLiteral("amp"), QStringLiteral("&")},      {QStringLiteral("lt"), QStringLiteral("<")},
        {QStringLiteral("gt"), QStringLiteral(">")},       {QStringLiteral("quot"), QStringLiteral("\"")},
        {QStringLiteral("apos"), QStringLiteral("'")},     {QStringLiteral("nbsp"), QStringLiteral("\u00a0")},
        {QStringLiteral("hellip"), QStringLiteral("\u2026")}, {QStringLiteral("mdash"), QStringLiteral("\u2014")},
        {QStringLiteral("ndash"), QStringLiteral("\u2013")}, {QStringLiteral("lsquo"), QStringLiteral("\u2018")},
        {QStringLiteral("rsquo"), QStringLiteral("\u2019")}, {QStringLiteral("ldquo"), QStringLiteral("\u201c")},
        {QStringLiteral("rdquo"), QStringLiteral("\u201d")}, {QStringLiteral("copy"), QStringLiteral("\u00a9")},
        {QStringLiteral("reg"), QStringLiteral("\u00ae")},  {QStringLiteral("middot"), QStringLiteral("\u00b7")},
    };
    static const QRegularExpression re(QStringLiteral("&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);"));
    QString out;
    qsizetype last = 0;
    auto it = re.globalMatch(s);
    while (it.hasNext()) {
        const auto m = it.next();
        const QString ent = m.captured(1);
        QString rep;
        if (ent.startsWith(QLatin1Char('#'))) {
            bool ok = false;
            const uint cp = (ent.size() > 1 && (ent[1] == QLatin1Char('x') || ent[1] == QLatin1Char('X')))
                                ? ent.mid(2).toUInt(&ok, 16)
                                : ent.mid(1).toUInt(&ok, 10);
            if (ok && cp > 0 && cp <= 0x10FFFF) {
                const char32_t c = cp;
                rep = QString::fromUcs4(&c, 1);
            }
        } else {
            rep = named.value(ent);
        }
        if (rep.isNull())
            continue;
        out += s.mid(last, m.capturedStart() - last) + rep;
        last = m.capturedEnd();
    }
    out += s.mid(last);
    return out;
}

} // namespace

// ---- 시간 --------------------------------------------------------------------

QString msToSrtTime(qint64 ms)
{
    const qint64 h = ms / 3600000;
    ms %= 3600000;
    const qint64 m = ms / 60000;
    ms %= 60000;
    const qint64 s = ms / 1000;
    ms %= 1000;
    return QStringLiteral("%1:%2:%3,%4")
        .arg(h, 2, 10, QLatin1Char('0'))
        .arg(m, 2, 10, QLatin1Char('0'))
        .arg(s, 2, 10, QLatin1Char('0'))
        .arg(ms, 3, 10, QLatin1Char('0'));
}

qint64 srtTimeToMs(const QString &time)
{
    const QStringList parts = time.trimmed().replace(QLatin1Char(','), QLatin1Char('.')).split(QLatin1Char(':'));
    if (parts.size() != 2 && parts.size() != 3)
        return 0;
    qint64 h = 0, m = 0, s = 0, frac = 0;
    const int n = int(parts.size());
    if (n == 3 && !toInt(parts[0], &h))
        return 0;
    if (!toInt(parts[n - 2], &m))
        return 0;
    const QStringList sp = parts[n - 1].split(QLatin1Char('.'));
    if (!toInt(sp[0], &s))
        return 0;
    if (sp.size() > 1) {
        // 파이썬: s_parts[1].ljust(3, '0')[:3]
        QString f = sp[1];
        while (f.size() < 3)
            f += QLatin1Char('0');
        if (!toInt(f.left(3), &frac))
            return 0;
    }
    return (h * 3600 + m * 60 + s) * 1000 + frac;
}

qint64 assTimeToMs(const QString &time)
{
    static const QRegularExpression re(QStringLiteral("^\\s*(\\d+):(\\d+):(\\d+)[.:](\\d+)"));
    const auto m = re.match(time);
    if (!m.hasMatch())
        return 0;
    const QString frac = m.captured(4);
    qint64 fracMs;
    if (frac.size() == 2) {
        fracMs = frac.toLongLong() * 10; // 센티초
    } else {
        QString f = frac;
        while (f.size() < 3)
            f += QLatin1Char('0');
        fracMs = f.left(3).toLongLong();
    }
    return ((m.captured(1).toLongLong() * 60 + m.captured(2).toLongLong()) * 60 + m.captured(3).toLongLong()) * 1000
        + fracMs;
}

// ---- 파일 읽기 ----------------------------------------------------------------

SubtitleText decodeSubtitleBytes(const QByteArray &raw)
{
    // 파이썬과 같은 순서: utf-8-sig, utf-8, cp949, euc-kr, utf-16, latin-1 — 처음으로 오류 없이 풀리는 것.
    // Qt 6.4의 QStringDecoder는 CP949/EUC-KR을 모르므로 GLib(iconv)의 g_convert를 씁니다.
    SubtitleText r;
    r.ok = true;
    {
        // 앞의 BOM은 떼어냄 (= utf-8-sig). Stateless: 끝에 잘린 멀티바이트 문자도 오류로 봐야 함
        QStringDecoder dec(QStringDecoder::Utf8, QStringConverter::Flag::Stateless);
        QString s = dec.decode(raw);
        if (!dec.hasError()) {
            r.content = s;
            r.encoding = QStringLiteral("utf-8-sig");
        }
    }
    if (r.encoding.isEmpty() && gConvertStrict(raw, "CP949", &r.content))
        r.encoding = QStringLiteral("cp949");
    if (r.encoding.isEmpty() && gConvertStrict(raw, "EUC-KR", &r.content))
        r.encoding = QStringLiteral("euc-kr");
    const bool utf16Bom = raw.startsWith("\xff\xfe") || raw.startsWith("\xfe\xff");
    if (r.encoding.isEmpty() && utf16Bom && raw.size() % 2 == 0) {
        // 파이썬 텍스트 모드의 'utf-16'은 BOM이 없으면 실패합니다 (BOM으로 엔디언 결정).
        QStringDecoder dec(QStringDecoder::Utf16, QStringConverter::Flag::Stateless);
        QString s = dec.decode(raw);
        if (!dec.hasError()) {
            r.content = s;
            r.encoding = QStringLiteral("utf-16");
        }
    }
    if (r.encoding.isEmpty()) {
        r.content = QString::fromLatin1(raw);
        r.encoding = QStringLiteral("latin-1");
    }
    // 파이썬 텍스트 모드의 줄바꿈 변환 (\r\n, \r → \n)
    if (r.content.contains(QLatin1Char('\r'))) {
        r.content.replace(QStringLiteral("\r\n"), QStringLiteral("\n"));
        r.content.replace(QLatin1Char('\r'), QLatin1Char('\n'));
    }
    return r;
}

SubtitleText readSubtitleText(const QString &filePath)
{
    QFile f(filePath);
    if (!f.open(QIODevice::ReadOnly))
        return {};
    return decodeSubtitleBytes(f.readAll());
}

// ---- SMI ------------------------------------------------------------------------

SubtitleEvents parseSmiToEvents(const QString &content)
{
    static const QRegularExpression syncRe(
        QStringLiteral("<sync\\s+start\\s*=\\s*[\"']?(\\d+)[\"']?[^>]*>(.*?)(?=<sync|$)"),
        QRegularExpression::CaseInsensitiveOption | QRegularExpression::DotMatchesEverythingOption);
    static const QRegularExpression brRe(QStringLiteral("<br\\s*/?>"), QRegularExpression::CaseInsensitiveOption);
    static const QRegularExpression tagRe(QStringLiteral("<[^>]+>"));

    QList<QPair<qint64, QString>> raw;
    auto it = syncRe.globalMatch(content);
    while (it.hasNext()) {
        const auto m = it.next();
        QString body = m.captured(2);
        body.replace(brRe, QStringLiteral("\n"));
        QString clean = body.remove(tagRe);
        clean.replace(QStringLiteral("&nbsp;"), QStringLiteral(" "))
            .replace(QStringLiteral("&lt;"), QStringLiteral("<"))
            .replace(QStringLiteral("&gt;"), QStringLiteral(">"))
            .replace(QStringLiteral("&amp;"), QStringLiteral("&"))
            .replace(QStringLiteral("&quot;"), QStringLiteral("\""));
        QStringList lines;
        for (const QString &l : splitLines(clean))
            if (!l.trimmed().isEmpty())
                lines << l.trimmed();
        raw.append({m.captured(1).toLongLong(), lines.join(QLatin1Char('\n'))});
    }

    SubtitleEvents events;
    for (int i = 0; i < raw.size(); ++i) {
        const qint64 start = raw[i].first;
        const QString &text = raw[i].second;
        if (text.isEmpty() || text == QLatin1String("&nbsp;") || text.trimmed().isEmpty())
            continue;
        qint64 end;
        if (i + 1 < raw.size()) {
            end = raw[i + 1].first;
            if (end - start > 7000) // 다음 싱크가 너무 멀면 (빈 줄 없이 끝난 자막) 4초만 표시
                end = start + 4000;
        } else {
            end = start + 4000;
        }
        if (end <= start)
            end = start + 1000;
        events.append({start, end, text});
    }
    return events;
}

// ---- SRT / VTT --------------------------------------------------------------------

SubtitleEvents parseSrtOrVttToEvents(const QString &content)
{
    static const QRegularExpression timeRe(QStringLiteral(
        "(\\d{1,2}:\\d{2}:\\d{2}[,\\.]\\d{1,3}|\\d{1,2}:\\d{2}[,\\.]\\d{1,3})\\s*-->\\s*"
        "(\\d{1,2}:\\d{2}:\\d{2}[,\\.]\\d{1,3}|\\d{1,2}:\\d{2}[,\\.]\\d{1,3})"));
    static const QRegularExpression tagRe(QStringLiteral("<[^>]+>"));
    static const QRegularExpression blockSep(QStringLiteral("\\n\\s*\\n"),
                                             QRegularExpression::UseUnicodePropertiesOption);
    SubtitleEvents events;
    const QStringList blocks = content.trimmed().split(blockSep);
    for (const QString &block : blocks) {
        QRegularExpressionMatch timeMatch;
        bool haveTime = false;
        QStringList textLines;
        for (const QString &rawLine : splitLines(block)) {
            const QString line = rawLine.trimmed();
            if (line.isEmpty())
                continue;
            const auto m = timeRe.match(line);
            if (m.hasMatch()) {
                timeMatch = m;
                haveTime = true;
            } else if (haveTime) {
                const QString clean = QString(line).remove(tagRe);
                if (!clean.isEmpty())
                    textLines << clean;
            }
        }
        if (haveTime && !textLines.isEmpty()) {
            const qint64 start = srtTimeToMs(timeMatch.captured(1));
            const qint64 end = srtTimeToMs(timeMatch.captured(2));
            if (end > start)
                events.append({start, end, textLines.join(QLatin1Char('\n'))});
        }
    }
    return events;
}

// ---- ASS (글자만) --------------------------------------------------------------------

QString assTextToPlain(const QString &text)
{
    static const QRegularExpression blockRe(QStringLiteral("\\{([^}]*)\\}"));
    // 태그 이름 뒤에 인자가 바로 붙는 경우(\fnComic Sans, \pos(…))가 있어 알려진 이름을 긴 것부터 맞춥니다.
    static const QRegularExpression tagRe([] {
        QStringList names = QStringLiteral("1c 2c 3c 4c 1a 2a 3a 4a alpha xbord ybord bord xshad yshad shad blur be "
                                           "fscx fscy fsp fs fn fe frx fry frz fr fax fay an a pos move org fade fad "
                                           "iclip clip kf ko k K q r b i u s p t c")
                                .split(QLatin1Char(' '));
        std::stable_sort(names.begin(), names.end(),
                         [](const QString &a, const QString &b) { return a.size() > b.size(); });
        return QStringLiteral("\\\\(") + names.join(QLatin1Char('|')) + QStringLiteral(")(\\([^)]*\\)|[^\\\\]*)");
    }());

    QString out;
    bool drawing = false; // \p1 이상: 벡터 그림 명령이라 글자가 아님
    qsizetype pos = 0;
    auto appendChunk = [&](const QString &chunk) {
        if (chunk.isEmpty() || drawing)
            return;
        QString c = chunk;
        c.replace(QStringLiteral("\\N"), QStringLiteral("\n"))
            .replace(QStringLiteral("\\n"), QStringLiteral("\n"))
            .replace(QStringLiteral("\\h"), QStringLiteral("\u00a0"));
        out += c;
    };
    auto blocks = blockRe.globalMatch(text);
    while (blocks.hasNext()) {
        const auto b = blocks.next();
        appendChunk(text.mid(pos, b.capturedStart() - pos));
        pos = b.capturedEnd();
        auto tags = tagRe.globalMatch(b.captured(1));
        while (tags.hasNext()) {
            const auto t = tags.next();
            if (t.captured(1) != QLatin1String("p"))
                continue;
            const QString arg = t.captured(2).trimmed();
            if (!arg.isEmpty() && !arg.startsWith(QLatin1Char('(')))
                drawing = num(arg, 0) > 0;
        }
    }
    appendChunk(text.mid(pos));
    return out.trimmed();
}

QString assBlockToPlain(const QString &payload)
{
    const QStringList f = splitMax(payload, QLatin1Char(','), 8);
    return f.size() == 9 ? assTextToPlain(f[8]) : QString();
}

SubtitleEvents parseAssToEvents(const QString &content)
{
    struct Row {
        SubtitleEvent ev;
        int order;
    };
    static const QStringList defaultFields = {
        QStringLiteral("layer"),   QStringLiteral("start"),   QStringLiteral("end"),
        QStringLiteral("style"),   QStringLiteral("name"),    QStringLiteral("marginl"),
        QStringLiteral("marginr"), QStringLiteral("marginv"), QStringLiteral("effect"),
        QStringLiteral("text")};
    QList<Row> rows;
    QString section;
    QStringList eventFields;
    int order = 0;
    for (const QString &raw : splitLines(content)) {
        const QString line = raw.trimmed();
        if (line.isEmpty() || line.startsWith(QLatin1Char(';')))
            continue;
        if (line.startsWith(QLatin1Char('[')) && line.endsWith(QLatin1Char(']'))) {
            section = line.mid(1, line.size() - 2).trimmed().toLower();
            continue;
        }
        if (section != QLatin1String("events"))
            continue;
        const int colon = line.indexOf(QLatin1Char(':'));
        const QString key = (colon < 0 ? line : line.left(colon)).trimmed().toLower();
        const QString value = colon < 0 ? QString() : line.mid(colon + 1);
        if (key == QLatin1String("format")) {
            eventFields.clear();
            for (const QString &f : value.split(QLatin1Char(',')))
                eventFields << f.trimmed().toLower();
        } else if (key == QLatin1String("dialogue")) {
            const QStringList &fields = eventFields.isEmpty() ? defaultFields : eventFields;
            const QStringList values = splitMax(value, QLatin1Char(','), int(fields.size()) - 1);
            QHash<QString, QString> row;
            for (int i = 0; i < qMin(fields.size(), values.size()); ++i)
                row.insert(fields[i], values[i]);
            const qint64 start = assTimeToMs(row.value(QStringLiteral("start")));
            const qint64 end = assTimeToMs(row.value(QStringLiteral("end")));
            if (end <= start)
                continue;
            const QString plain = assTextToPlain(row.value(QStringLiteral("text")));
            if (plain.isEmpty())
                continue; // 그리기만 있는 대사 등
            rows.append({{start, end, plain}, order++});
        }
    }
    std::stable_sort(rows.begin(), rows.end(), [](const Row &a, const Row &b) {
        return a.ev.startMs != b.ev.startMs ? a.ev.startMs < b.ev.startMs : a.order < b.order;
    });
    SubtitleEvents events;
    events.reserve(rows.size());
    for (const Row &r : rows)
        events.append(r.ev);
    return events;
}

SubtitleEvents parseSubtitleFileEvents(const QString &filePath)
{
    const SubtitleText t = readSubtitleText(filePath);
    if (!t.ok) {
        qCWarning(lcSubParse) << "⚠️ 자막 파싱 실패 (" << filePath << "): 파일을 열 수 없음";
        return {};
    }
    const QString ext = extOf(baseName(filePath)).toLower();
    if (ext == QLatin1String(".smi"))
        return parseSmiToEvents(t.content);
    if (ext == QLatin1String(".ass") || ext == QLatin1String(".ssa"))
        return parseAssToEvents(t.content);
    return parseSrtOrVttToEvents(t.content);
}

// ---- 이름·언어 ----------------------------------------------------------------------

bool isAiSubtitle(const QString &filePath)
{
    return baseName(filePath).toLower().contains(QLatin1String(".ai."));
}

QString subtitleColor(const QString &filePath, int index)
{
    // 파이썬과 같이 확장자까지 포함한 파일 이름에서 찾습니다.
    const QString stem = baseName(filePath).toLower();
    if (isAiSubtitle(filePath))
        return kAiSubtitleColor;
    if (containsAny(stem, {".ko", ".kor", ".kr", "_ko", "_kor", "_kr", ".korean", "한국어", "한글"}))
        return languageColor(QStringLiteral("ko"));
    if (containsAny(stem, {".en", ".eng", "_en", "_eng", ".english", "영어", "영문"}))
        return languageColor(QStringLiteral("en"));
    if (containsAny(stem, {".zh", ".chi", ".zho", "_zh", "_chi", ".chinese", "중국어", "중문", ".cmn", "zh-tw", "zh-cn"}))
        return languageColor(QStringLiteral("zh"));
    if (containsAny(stem, {".ja", ".jpn", ".jp", "_ja", "_jpn", ".japanese", "일본어", "일어"}))
        return languageColor(QStringLiteral("ja"));
    if (containsAny(stem, {".es", ".spa", "_es", "_spa", ".spanish", "스페인어"}))
        return languageColor(QStringLiteral("es"));
    if (containsAny(stem, {".fr", ".fre", ".fra", "_fr", "_fre", ".french", "프랑스어"}))
        return languageColor(QStringLiteral("fr"));
    if (containsAny(stem, {".de", ".ger", ".deu", "_de", "_ger", ".german", "독일어"}))
        return languageColor(QStringLiteral("de"));
    if (containsAny(stem, {".ru", ".rus", "_ru", "_rus", ".russian", "러시아어"}))
        return languageColor(QStringLiteral("ru"));
    const int n = int(kFallbackPalette.size());
    return kFallbackPalette[((index % n) + n) % n];
}

QString subtitleLabel(const QString &filePath)
{
    const QString base = baseName(filePath);
    const QString stemLower = stemOf(base).toLower();
    if (isAiSubtitle(filePath)) {
        // "🤖 AI " + 언어 (.ai.를 뺀 이름으로 아래 규칙을 다시 적용)
        const QString plain = subtitleLabel(base.toLower().replace(QLatin1String(".ai."), QLatin1String(".")));
        QString language = QStringLiteral("자막");
        if (!plain.startsWith(QStringLiteral("📄"))) {
            const QString head = plain.section(QStringLiteral(" ("), 0, 0);
            const int sp = head.indexOf(QLatin1Char(' '));
            language = sp < 0 ? head : head.mid(sp + 1);
        }
        return QStringLiteral("🤖 AI %1 (%2)").arg(language, base);
    }
    if (containsAny(stemLower, {".ko", ".kor", ".kr", "_ko", "_kor", "_kr", ".korean", "한국어", "한글"}))
        return QStringLiteral("🇰🇷 한국어 (%1)").arg(base);
    if (containsAny(stemLower, {".en", ".eng", "_en", "_eng", ".english", "영어", "영문"}))
        return QStringLiteral("🇺🇸 영어 (%1)").arg(base);
    if (containsAny(stemLower, {".ja", ".jpn", ".jp", "_ja", "_jpn", ".japanese", "일본어", "일어"}))
        return QStringLiteral("🇯🇵 일본어 (%1)").arg(base);
    if (containsAny(stemLower, {".zh", ".chi", ".zho", "_zh", "_chi", ".chinese", "중국어", "중문", ".cmn"}))
        return QStringLiteral("🇨🇳 중국어 (%1)").arg(base);
    if (containsAny(stemLower, {".es", ".spa", "_es", "_spa", ".spanish", "스페인어"}))
        return QStringLiteral("🇪🇸 스페인어 (%1)").arg(base);
    if (containsAny(stemLower, {".fr", ".fre", ".fra", "_fr", "_fre", ".french", "프랑스어"}))
        return QStringLiteral("🇫🇷 프랑스어 (%1)").arg(base);
    if (containsAny(stemLower, {".de", ".ger", ".deu", "_de", "_ger", ".german", "독일어"}))
        return QStringLiteral("🇩🇪 독일어 (%1)").arg(base);
    return QStringLiteral("📄 %1").arg(base);
}

QString stripMarkup(const QString &text)
{
    static const QRegularExpression tagRe(QStringLiteral("<[^>]+>"));
    return htmlUnescape(QString(text).remove(tagRe)).trimmed();
}

// ---- 탐색 --------------------------------------------------------------------------

QString cachedAiSubtitleStem(const QString &videoPath)
{
    // <영상 이름>.<폴더 해시 8자> — 파이썬 hashlib.sha1(abspath 폴더)와 같아야 기존 캐시를 이어 씁니다.
    const QString abs = absPath(videoPath);
    const QByteArray hash = QCryptographicHash::hash(dirOf(abs).toUtf8(), QCryptographicHash::Sha1).toHex();
    return stemOf(baseName(videoPath)) + QLatin1Char('.') + QString::fromLatin1(hash.left(8));
}

static bool hasSubtitleExt(const QString &name)
{
    const QString lower = name.toLower();
    for (const QString &e : kSubtitleExts)
        if (lower.endsWith(e))
            return true;
    return false;
}

QStringList findCachedAiSubtitles(const QString &videoPath, const QString &cacheDir)
{
    const QString dir = cacheDir.isEmpty() ? paths::aiSubtitleCacheDir() : cacheDir;
    QDir d(dir);
    if (!d.exists())
        return {};
    const QString hashed = cachedAiSubtitleStem(videoPath) + QLatin1Char('.');
    const QString legacy = stemOf(baseName(videoPath)) + QStringLiteral(".ai."); // 해시 없이 저장하던 예전 이름
    QStringList names = d.entryList(QDir::AllEntries | QDir::Hidden | QDir::System | QDir::NoDotAndDotDot);
    std::sort(names.begin(), names.end());
    QStringList out;
    for (const QString &n : names)
        if ((n.startsWith(hashed) || n.startsWith(legacy)) && hasSubtitleExt(n))
            out << joinPath(dir, n);
    return out;
}

QStringList findAllMatchingSubtitles(const QString &videoPath)
{
    const QString dirName = dirOf(absPath(videoPath));
    const QString stem = stemOf(baseName(videoPath));
    const QString stemLower = stem.toLower();

    QStringList found;
    QSet<QString> seen;
    auto add = [&](const QString &p) {
        if (seen.contains(p))
            return false;
        seen.insert(p);
        found << p;
        return true;
    };

    // 1. 같은 파일 이름 (확장자 대소문자 둘 다)
    for (const QString &ext : kSubtitleExts)
        for (const QString &e : {ext, ext.toUpper()}) {
            const QString cand = joinPath(dirName, stem + e);
            if (!seen.contains(cand) && QFileInfo(cand).isFile())
                add(cand);
        }

    // 같은 폴더의 영상들 — 자막 파일이 어느 영상의 것인지 판단하는 데 씁니다.
    QStringList dirFiles;
    const QStringList entries =
        QDir(dirName).entryList(QDir::Files | QDir::Hidden | QDir::System | QDir::NoDotAndDotDot);
    for (const QString &f : entries)
        if (QFileInfo(joinPath(dirName, f)).isFile())
            dirFiles << f;
    QSet<QString> videoStems;
    for (const QString &f : dirFiles)
        if (kVideoExts.contains(extOf(f).toLower()))
            videoStems.insert(stemOf(f).toLower());
    videoStems.insert(stemLower);

    // 자막 이름에 가장 길게 들어맞는 영상 이름 (없으면 null). ep1/ep10처럼 앞이 같아도 더 구체적인 쪽이 가져갑니다.
    // 이름이 영상 이름으로 "시작"하는 경우를 우선 — "포함"만 보면 b.ai.ko.srt가 영상 "a"에도 걸립니다.
    auto owner = [&](const QString &subLower) -> QString {
        auto best = [](const QStringList &m) {
            QString b;
            for (const QString &v : m)
                if (b.isNull() || v.size() > b.size() || (v.size() == b.size() && v > b))
                    b = v;
            return b;
        };
        QStringList matches;
        for (const QString &v : videoStems)
            if (subLower.startsWith(v))
                matches << v;
        if (matches.isEmpty())
            for (const QString &v : videoStems)
                if (subLower.contains(v))
                    matches << v;
        return best(matches);
    };

    QStringList subtitleNames;
    for (const QString &f : dirFiles)
        if (hasSubtitleExt(f))
            subtitleNames << f;

    // 2. 언어 태그가 붙은 자막 (movie.ko.srt 등) — 이 영상이 주인인 것만
    for (const QString &f : subtitleNames) {
        const QString cand = joinPath(dirName, f);
        if (!seen.contains(cand) && owner(f.toLower()) == stemLower)
            add(cand);
    }
    // 3. 그래도 없으면 어느 영상에도 속하지 않는 자막만 (다른 영상의 자막·AI 자막을 빌려오지 않음)
    if (found.isEmpty())
        for (const QString &f : subtitleNames) {
            const QString cand = joinPath(dirName, f);
            if (!seen.contains(cand) && owner(f.toLower()).isNull())
                add(cand);
        }
    // 영상 폴더에 쓸 수 없어 캐시에 저장된 AI 자막
    for (const QString &p : findCachedAiSubtitles(videoPath))
        add(p);

    // 한국어, 영어, 일본어 순으로 앞에
    auto rank = [](const QString &path) {
        const QString lbl = subtitleLabel(path);
        if (lbl.contains(QStringLiteral("한국어")))
            return 0;
        if (lbl.contains(QStringLiteral("영어")))
            return 1;
        if (lbl.contains(QStringLiteral("일본어")))
            return 2;
        return 3;
    };
    std::sort(found.begin(), found.end(), [&](const QString &a, const QString &b) {
        const int ra = rank(a), rb = rank(b);
        return ra != rb ? ra < rb : a < b;
    });
    return found;
}

} // namespace jvp::subtitles
