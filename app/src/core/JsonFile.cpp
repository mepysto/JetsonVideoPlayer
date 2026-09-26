#include "JsonFile.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QSaveFile>

namespace jvp::json {

QJsonValue read(const QString &path, bool *ok)
{
    if (ok)
        *ok = false;
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return QJsonValue(QJsonValue::Undefined);
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(f.readAll(), &err);
    if (err.error != QJsonParseError::NoError)
        return QJsonValue(QJsonValue::Undefined);
    if (ok)
        *ok = true;
    // QJsonDocument는 객체/배열만 담습니다 (파이썬 json은 최상위 숫자 등도 허용하지만 어차피 형식 오류로 버림)
    if (doc.isObject())
        return doc.object();
    if (doc.isArray())
        return doc.array();
    return QJsonValue(QJsonValue::Null);
}

QJsonObject readObject(const QString &path, bool *ok)
{
    bool readOk = false;
    const QJsonValue v = read(path, &readOk);
    if (ok)
        *ok = readOk && v.isObject();
    return v.toObject();
}

QJsonArray readArray(const QString &path, bool *ok)
{
    bool readOk = false;
    const QJsonValue v = read(path, &readOk);
    if (ok)
        *ok = readOk && v.isArray();
    return v.toArray();
}

bool writeBytesAtomic(const QString &path, const QByteArray &bytes, QString *error)
{
    const QString dir = QFileInfo(path).absolutePath();
    if (!QDir().mkpath(dir)) {
        if (error)
            *error = QStringLiteral("cannot create %1").arg(dir);
        return false;
    }
    QSaveFile f(path);
    if (!f.open(QIODevice::WriteOnly)) {
        if (error)
            *error = f.errorString();
        return false;
    }
    if (f.write(bytes) != bytes.size() || !f.commit()) {
        if (error)
            *error = f.errorString();
        return false;
    }
    return true;
}

bool writeAtomic(const QString &path, const QJsonValue &value, QString *error)
{
    QJsonDocument doc;
    if (value.isArray())
        doc.setArray(value.toArray());
    else
        doc.setObject(value.toObject());
    return writeBytesAtomic(path, doc.toJson(QJsonDocument::Indented), error);
}

QByteArray serializeOrderedObject(const QList<QPair<QString, QJsonValue>> &items)
{
    // 값 하나씩 배열로 감싸 직렬화한 뒤 괄호를 벗겨 씁니다 (문자열 이스케이프·숫자 형식을 Qt에 맡기기 위해)
    auto one = [](const QJsonValue &v) {
        QByteArray s = QJsonDocument(QJsonArray{v}).toJson(QJsonDocument::Compact);
        return s.mid(1, s.size() - 2);
    };
    QByteArray out = "{";
    bool first = true;
    for (const auto &[key, value] : items) {
        out += first ? "\n  " : ",\n  ";
        first = false;
        out += one(key) + ": " + one(value);
    }
    out += first ? "}\n" : "\n}\n";
    return out;
}

} // namespace jvp::json
