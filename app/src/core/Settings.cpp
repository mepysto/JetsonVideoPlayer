#include "Settings.h"

#include "JsonFile.h"
#include "Paths.h"

#include <QHash>
#include <QJsonObject>
#include <QLoggingCategory>
#include <QMutexLocker>
#include <QPair>
#include <cmath>
#include <limits>

Q_LOGGING_CATEGORY(lcSettings, "jvp.settings")

namespace jvp {

namespace {

using Entry = QPair<QString, QVariant>;

// 파이썬 settings.DEFAULTS와 같은 키·타입 (int/float/bool/str/list 구분이 검증 규칙을 정합니다)
const QList<Entry> &defaults()
{
    static const QList<Entry> d = {
        {"volume", 100},
        {"muted", false},
        {"subtitle_font_scale", 1.0},
        {"repeat_mode", QStringLiteral("all")},
        {"sidebar_width", 360},
        {"sidebar_visible", true},
        {"window_width", 1280},
        {"window_height", 720},
        {"window_maximized", false},
        {"hud_visible", false},
        {"embedded_subs_enabled", true},
        {"subtitle_ass_styles", true},   // ASS/SSA 자막을 원래 글꼴·색·위치로 그림
        {"time_display_remaining", false},
        {"playlist_sort", QStringLiteral("name")},
        {"autoplay_countdown", true},
        {"night_mode", false},
        {"loudness_normalize", true},    // 영상마다 다른 음량을 비슷하게 (EBU R128)
        {"eq_preset", QStringLiteral("flat")},
        {"opensubtitles_languages", QStringLiteral("ko,en")},
        {"audio_passthrough", false},
        {"hdr_tonemap", true},
        {"remote_pin", QString()},
        {"remote_lan_only", true},
        {"mini_width", 480},
        {"mini_x", -1},                  // -1: 화면 오른쪽 아래
        {"mini_y", -1},
        {"network_locations", QVariantList()},   // [{"uri", "path", "name"}]
        {"whisper_model", QStringLiteral("small-q5_1")},
        {"whisper_language", QStringLiteral("auto")},
        {"whisper_translate", false},
        {"youtube_auto_ai_subtitles", false},
        {"translate_target", QStringLiteral("ko")},
        {"translate_backend", QStringLiteral("auto")},
        {"whisper_auto_translate", false},
        // Qt 버전에서 추가: 화면 구성 (auto: 화면 크기·입력 장치로 판단)
        {"ui_mode", QStringLiteral("auto")},
    };
    return d;
}

const QHash<QString, QVariant> &defaultsMap()
{
    static const QHash<QString, QVariant> m = [] {
        QHash<QString, QVariant> h;
        for (const auto &[k, v] : defaults())
            h.insert(k, v);
        return h;
    }();
    return m;
}

const QHash<QString, QPair<double, double>> &limits()
{
    static const QHash<QString, QPair<double, double>> l = {
        {"volume", {0, 200}},
        {"subtitle_font_scale", {0.6, 1.6}},
        {"sidebar_width", {200, 2000}},
        {"window_width", {480, 10000}},
        {"window_height", {320, 10000}},
        {"mini_width", {240, 1280}},
        {"mini_x", {-1, 20000}},
        {"mini_y", {-1, 20000}},
    };
    return l;
}

const QHash<QString, QStringList> &choices()
{
    static const QHash<QString, QStringList> c = {
        {"repeat_mode", {"all", "one", "none", "shuffle"}},
        {"playlist_sort", {"name", "mtime", "size"}},
        {"translate_target", {"ko", "en", "ja", "zh"}},
        {"translate_backend", {"auto", "local", "claude"}},
        {"eq_preset", {"flat", "dialogue", "bass", "treble", "quiet"}},
        {"ui_mode", {"auto", "desktop", "tv"}},
    };
    return c;
}

bool isNumber(const QVariant &v)
{
    // 파이썬의 isinstance(v, (int, float)) and not bool — bool은 숫자로 받지 않습니다
    switch (v.metaType().id()) {
    case QMetaType::Int:
    case QMetaType::UInt:
    case QMetaType::Long:
    case QMetaType::ULong:
    case QMetaType::LongLong:
    case QMetaType::ULongLong:
    case QMetaType::Short:
    case QMetaType::UShort:
    case QMetaType::Double:
    case QMetaType::Float:
        return true;
    default:
        return false;
    }
}

} // namespace

Settings::Settings(const QString &path, QObject *parent)
    : QObject(parent), m_path(path.isEmpty() ? paths::configDir() + QStringLiteral("/settings.json") : path)
{
    for (const auto &[k, v] : defaults())
        m_values.insert(k, v);
    load();
}

Settings *Settings::instance()
{
    static Settings s;
    return &s;
}

QStringList Settings::keys()
{
    QStringList out;
    for (const auto &e : defaults())
        out << e.first;
    return out;
}

QVariant Settings::defaultValue(const QString &key) { return defaultsMap().value(key); }

bool Settings::isKnownKey(const QString &key) { return defaultsMap().contains(key); }

QVariant Settings::validate(const QString &key, const QVariant &value)
{
    const auto it = defaultsMap().constFind(key);
    if (it == defaultsMap().constEnd())
        return {};
    const QVariant &def = it.value();
    switch (def.metaType().id()) {
    case QMetaType::Bool:
        return value.metaType().id() == QMetaType::Bool ? value : def;
    case QMetaType::Int:
    case QMetaType::Double: {
        if (!isNumber(value))
            return def;
        double v = value.toDouble();
        if (std::isnan(v))
            return def;
        const auto lim = limits().value(key, {-std::numeric_limits<double>::infinity(),
                                               std::numeric_limits<double>::infinity()});
        v = std::max(lim.first, std::min(lim.second, v));
        if (def.metaType().id() == QMetaType::Int) {
            // 파이썬 int(value)처럼 0 쪽으로 버림
            v = std::trunc(v);
            if (v > std::numeric_limits<int>::max() || v < std::numeric_limits<int>::min())
                return def;
            return QVariant(static_cast<int>(v));
        }
        return QVariant(v);
    }
    case QMetaType::QVariantList: {
        const int t = value.metaType().id();
        if (t == QMetaType::QVariantList || t == QMetaType::QStringList)
            return QVariant(value.toList());
        // QML의 JS 배열은 QJSValue로 들어올 수 있습니다
        if (value.metaType().name() == QByteArrayLiteral("QJSValue") && value.canConvert<QVariantList>())
            return QVariant(value.value<QVariantList>());
        return def;
    }
    case QMetaType::QString: {
        if (value.metaType().id() != QMetaType::QString)
            return def;
        const auto c = choices().constFind(key);
        if (c != choices().constEnd() && !c->contains(value.toString()))
            return def;
        return value;
    }
    default:
        return def;
    }
}

void Settings::load()
{
    const QJsonObject data = json::readObject(m_path);
    QMutexLocker lock(&m_mutex);
    for (const auto &e : defaults()) {
        const auto it = data.constFind(e.first);
        if (it != data.constEnd())
            m_values.insert(e.first, validate(e.first, it->toVariant()));
    }
    m_saved = m_values;
}

QVariant Settings::value(const QString &key) const
{
    QMutexLocker lock(&m_mutex);
    const auto it = m_values.constFind(key);
    if (it == m_values.constEnd()) {
        qCWarning(lcSettings) << "알 수 없는 설정 키:" << key;
        return {};
    }
    return it.value();
}

QVariant Settings::setValue(const QString &key, const QVariant &value)
{
    if (!isKnownKey(key)) {
        qCWarning(lcSettings) << "⚠️ 알 수 없는 설정 키는 무시합니다:" << key;
        return {};
    }
    const QVariant v = validate(key, value);
    bool changed = false;
    {
        QMutexLocker lock(&m_mutex);
        changed = m_values.value(key) != v;
        m_values.insert(key, v);
    }
    if (changed)
        emit valueChanged(key);
    return v;
}

void Settings::update(const QVariantMap &values)
{
    for (auto it = values.constBegin(); it != values.constEnd(); ++it)
        setValue(it.key(), it.value());
}

bool Settings::save()
{
    QMutexLocker lock(&m_mutex);
    if (m_values == m_saved)
        return false;
    QJsonObject obj;
    for (auto it = m_values.constBegin(); it != m_values.constEnd(); ++it)
        obj.insert(it.key(), QJsonValue::fromVariant(it.value()));
    QString error;
    if (!json::writeAtomic(m_path, obj, &error)) {
        qCWarning(lcSettings).noquote() << "⚠️ 설정 저장 실패:" << error;
        return false;
    }
    m_saved = m_values;
    return true;
}

} // namespace jvp
