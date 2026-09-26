#pragma once
// JSON 파일 읽기/쓰기 도우미.
// 쓰기는 QSaveFile(임시 파일에 쓴 뒤 교체)로 — 저장 도중 전원이 꺼져도 기존 파일이 손상되지 않게 합니다.

#include <QByteArray>
#include <QJsonArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QList>
#include <QPair>
#include <QString>

namespace jvp::json {

// 파일을 읽어 JSON 값으로. 없거나 손상됐으면 Undefined (ok=false)
QJsonValue read(const QString &path, bool *ok = nullptr);
// 최상위가 객체/배열일 때만 그 값, 아니면 빈 값
QJsonObject readObject(const QString &path, bool *ok = nullptr);
QJsonArray readArray(const QString &path, bool *ok = nullptr);

// 부모 폴더를 만들고 원자적으로 씁니다. 실패하면 false (error에 사유)
bool writeBytesAtomic(const QString &path, const QByteArray &bytes, QString *error = nullptr);
bool writeAtomic(const QString &path, const QJsonValue &value, QString *error = nullptr);

// QJsonObject는 키를 정렬해 버리므로, 순서가 의미 있는 저장소(LRU)는 이 함수로 순서를 지켜 씁니다.
QByteArray serializeOrderedObject(const QList<QPair<QString, QJsonValue>> &items);

} // namespace jvp::json
