/****************************************************************************
** Meta object code from reading C++ file 'PlayerEngine.h'
**
** Created by: The Qt Meta Object Compiler version 69 (Qt 6.11.3)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include "../../../../src/media/PlayerEngine.h"
#include <QtCore/qmetatype.h>

#include <QtCore/qtmochelpers.h>

#include <memory>


#include <QtCore/qxptype_traits.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'PlayerEngine.h' doesn't include <QObject>."
#elif Q_MOC_OUTPUT_REVISION != 69
#error "This file was generated using the moc from 6.11.3. It"
#error "cannot be used with the include files from this version of Qt."
#error "(The moc has changed too much.)"
#endif

#ifndef Q_CONSTINIT
#define Q_CONSTINIT
#endif

QT_WARNING_PUSH
QT_WARNING_DISABLE_DEPRECATED
QT_WARNING_DISABLE_GCC("-Wuseless-cast")
namespace {
struct qt_meta_tag_ZN3jvp12PlayerEngineE_t {};
} // unnamed namespace

template <> constexpr inline auto jvp::PlayerEngine::qt_create_metaobjectdata<qt_meta_tag_ZN3jvp12PlayerEngineE_t>()
{
    namespace QMC = QtMocConstants;
    QtMocHelpers::StringRefStorage qt_stringData {
        "jvp::PlayerEngine",
        "playingChanged",
        "",
        "playing",
        "asyncDone",
        "endOfStream",
        "errorOccurred",
        "message",
        "debug",
        "fromPassthrough",
        "streamsChanged",
        "chaptersFound",
        "QVariantList",
        "chapters",
        "decoderSelected",
        "factory",
        "hardware",
        "embeddedText",
        "startMs",
        "endMs",
        "text",
        "embeddedAss",
        "header",
        "block"
    };

    QtMocHelpers::UintData qt_methods {
        // Signal 'playingChanged'
        QtMocHelpers::SignalData<void(bool)>(1, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Bool, 3 },
        }}),
        // Signal 'asyncDone'
        QtMocHelpers::SignalData<void()>(4, 2, QMC::AccessPublic, QMetaType::Void),
        // Signal 'endOfStream'
        QtMocHelpers::SignalData<void()>(5, 2, QMC::AccessPublic, QMetaType::Void),
        // Signal 'errorOccurred'
        QtMocHelpers::SignalData<void(const QString &, const QString &, bool)>(6, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 7 }, { QMetaType::QString, 8 }, { QMetaType::Bool, 9 },
        }}),
        // Signal 'streamsChanged'
        QtMocHelpers::SignalData<void()>(10, 2, QMC::AccessPublic, QMetaType::Void),
        // Signal 'chaptersFound'
        QtMocHelpers::SignalData<void(const QVariantList &)>(11, 2, QMC::AccessPublic, QMetaType::Void, {{
            { 0x80000000 | 12, 13 },
        }}),
        // Signal 'decoderSelected'
        QtMocHelpers::SignalData<void(const QString &, bool)>(14, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 15 }, { QMetaType::Bool, 16 },
        }}),
        // Signal 'embeddedText'
        QtMocHelpers::SignalData<void(qint64, qint64, const QString &)>(17, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::LongLong, 18 }, { QMetaType::LongLong, 19 }, { QMetaType::QString, 20 },
        }}),
        // Signal 'embeddedAss'
        QtMocHelpers::SignalData<void(const QString &, qint64, qint64, const QString &)>(21, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 22 }, { QMetaType::LongLong, 18 }, { QMetaType::LongLong, 19 }, { QMetaType::QString, 23 },
        }}),
    };
    QtMocHelpers::UintData qt_properties {
    };
    QtMocHelpers::UintData qt_enums {
    };
    return QtMocHelpers::metaObjectData<PlayerEngine, qt_meta_tag_ZN3jvp12PlayerEngineE_t>(QMC::MetaObjectFlag{}, qt_stringData,
            qt_methods, qt_properties, qt_enums);
}
Q_CONSTINIT const QMetaObject jvp::PlayerEngine::staticMetaObject = { {
    QMetaObject::SuperData::link<QObject::staticMetaObject>(),
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp12PlayerEngineE_t>.stringdata,
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp12PlayerEngineE_t>.data,
    qt_static_metacall,
    nullptr,
    qt_staticMetaObjectRelocatingContent<qt_meta_tag_ZN3jvp12PlayerEngineE_t>.metaTypes,
    nullptr
} };

void jvp::PlayerEngine::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    auto *_t = static_cast<PlayerEngine *>(_o);
    if (_c == QMetaObject::InvokeMetaMethod) {
        switch (_id) {
        case 0: _t->playingChanged((*reinterpret_cast<std::add_pointer_t<bool>>(_a[1]))); break;
        case 1: _t->asyncDone(); break;
        case 2: _t->endOfStream(); break;
        case 3: _t->errorOccurred((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[2])),(*reinterpret_cast<std::add_pointer_t<bool>>(_a[3]))); break;
        case 4: _t->streamsChanged(); break;
        case 5: _t->chaptersFound((*reinterpret_cast<std::add_pointer_t<QVariantList>>(_a[1]))); break;
        case 6: _t->decoderSelected((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<bool>>(_a[2]))); break;
        case 7: _t->embeddedText((*reinterpret_cast<std::add_pointer_t<qint64>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<qint64>>(_a[2])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[3]))); break;
        case 8: _t->embeddedAss((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<qint64>>(_a[2])),(*reinterpret_cast<std::add_pointer_t<qint64>>(_a[3])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[4]))); break;
        default: ;
        }
    }
    if (_c == QMetaObject::IndexOfMethod) {
        if (QtMocHelpers::indexOfMethod<void (PlayerEngine::*)(bool )>(_a, &PlayerEngine::playingChanged, 0))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlayerEngine::*)()>(_a, &PlayerEngine::asyncDone, 1))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlayerEngine::*)()>(_a, &PlayerEngine::endOfStream, 2))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlayerEngine::*)(const QString & , const QString & , bool )>(_a, &PlayerEngine::errorOccurred, 3))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlayerEngine::*)()>(_a, &PlayerEngine::streamsChanged, 4))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlayerEngine::*)(const QVariantList & )>(_a, &PlayerEngine::chaptersFound, 5))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlayerEngine::*)(const QString & , bool )>(_a, &PlayerEngine::decoderSelected, 6))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlayerEngine::*)(qint64 , qint64 , const QString & )>(_a, &PlayerEngine::embeddedText, 7))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlayerEngine::*)(const QString & , qint64 , qint64 , const QString & )>(_a, &PlayerEngine::embeddedAss, 8))
            return;
    }
}

const QMetaObject *jvp::PlayerEngine::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *jvp::PlayerEngine::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp12PlayerEngineE_t>.strings))
        return static_cast<void*>(this);
    return QObject::qt_metacast(_clname);
}

int jvp::PlayerEngine::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QObject::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 9)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 9;
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 9)
            *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType();
        _id -= 9;
    }
    return _id;
}

// SIGNAL 0
void jvp::PlayerEngine::playingChanged(bool _t1)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 0, nullptr, _t1);
}

// SIGNAL 1
void jvp::PlayerEngine::asyncDone()
{
    QMetaObject::activate(this, &staticMetaObject, 1, nullptr);
}

// SIGNAL 2
void jvp::PlayerEngine::endOfStream()
{
    QMetaObject::activate(this, &staticMetaObject, 2, nullptr);
}

// SIGNAL 3
void jvp::PlayerEngine::errorOccurred(const QString & _t1, const QString & _t2, bool _t3)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 3, nullptr, _t1, _t2, _t3);
}

// SIGNAL 4
void jvp::PlayerEngine::streamsChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 4, nullptr);
}

// SIGNAL 5
void jvp::PlayerEngine::chaptersFound(const QVariantList & _t1)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 5, nullptr, _t1);
}

// SIGNAL 6
void jvp::PlayerEngine::decoderSelected(const QString & _t1, bool _t2)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 6, nullptr, _t1, _t2);
}

// SIGNAL 7
void jvp::PlayerEngine::embeddedText(qint64 _t1, qint64 _t2, const QString & _t3)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 7, nullptr, _t1, _t2, _t3);
}

// SIGNAL 8
void jvp::PlayerEngine::embeddedAss(const QString & _t1, qint64 _t2, qint64 _t3, const QString & _t4)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 8, nullptr, _t1, _t2, _t3, _t4);
}
QT_WARNING_POP
