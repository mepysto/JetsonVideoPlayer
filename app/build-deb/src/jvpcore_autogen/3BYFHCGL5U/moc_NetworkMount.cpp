/****************************************************************************
** Meta object code from reading C++ file 'NetworkMount.h'
**
** Created by: The Qt Meta Object Compiler version 69 (Qt 6.11.3)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include "../../../../src/services/NetworkMount.h"
#include <QtCore/qmetatype.h>

#include <QtCore/qtmochelpers.h>

#include <memory>


#include <QtCore/qxptype_traits.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'NetworkMount.h' doesn't include <QObject>."
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
struct qt_meta_tag_ZN3jvp12NetworkMountE_t {};
} // unnamed namespace

template <> constexpr inline auto jvp::NetworkMount::qt_create_metaobjectdata<qt_meta_tag_ZN3jvp12NetworkMountE_t>()
{
    namespace QMC = QtMocConstants;
    QtMocHelpers::StringRefStorage qt_stringData {
        "jvp::NetworkMount",
        "passwordRequested",
        "",
        "message",
        "defaultUser",
        "defaultDomain",
        "flags",
        "questionAsked",
        "choices",
        "finished",
        "uri",
        "localPath",
        "error",
        "reply",
        "user",
        "password",
        "domain",
        "remember",
        "answer",
        "choice",
        "cancel",
        "AskFlag",
        "NeedPassword",
        "NeedUsername",
        "NeedDomain",
        "SavingSupported",
        "AnonymousSupported"
    };

    QtMocHelpers::UintData qt_methods {
        // Signal 'passwordRequested'
        QtMocHelpers::SignalData<void(const QString &, const QString &, const QString &, int)>(1, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 3 }, { QMetaType::QString, 4 }, { QMetaType::QString, 5 }, { QMetaType::Int, 6 },
        }}),
        // Signal 'questionAsked'
        QtMocHelpers::SignalData<void(const QString &, const QStringList &)>(7, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 3 }, { QMetaType::QStringList, 8 },
        }}),
        // Signal 'finished'
        QtMocHelpers::SignalData<void(const QString &, const QString &, const QString &)>(9, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 10 }, { QMetaType::QString, 11 }, { QMetaType::QString, 12 },
        }}),
        // Slot 'reply'
        QtMocHelpers::SlotData<void(const QString &, const QString &, const QString &, bool)>(13, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 14 }, { QMetaType::QString, 15 }, { QMetaType::QString, 16 }, { QMetaType::Bool, 17 },
        }}),
        // Slot 'answer'
        QtMocHelpers::SlotData<void(int)>(18, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 19 },
        }}),
        // Slot 'cancel'
        QtMocHelpers::SlotData<void()>(20, 2, QMC::AccessPublic, QMetaType::Void),
    };
    QtMocHelpers::UintData qt_properties {
    };
    QtMocHelpers::UintData qt_enums {
        // enum 'AskFlag'
        QtMocHelpers::EnumData<enum AskFlag>(21, 21, QMC::EnumFlags{}).add({
            {   22, AskFlag::NeedPassword },
            {   23, AskFlag::NeedUsername },
            {   24, AskFlag::NeedDomain },
            {   25, AskFlag::SavingSupported },
            {   26, AskFlag::AnonymousSupported },
        }),
    };
    return QtMocHelpers::metaObjectData<NetworkMount, qt_meta_tag_ZN3jvp12NetworkMountE_t>(QMC::MetaObjectFlag{}, qt_stringData,
            qt_methods, qt_properties, qt_enums);
}
Q_CONSTINIT const QMetaObject jvp::NetworkMount::staticMetaObject = { {
    QMetaObject::SuperData::link<QObject::staticMetaObject>(),
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp12NetworkMountE_t>.stringdata,
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp12NetworkMountE_t>.data,
    qt_static_metacall,
    nullptr,
    qt_staticMetaObjectRelocatingContent<qt_meta_tag_ZN3jvp12NetworkMountE_t>.metaTypes,
    nullptr
} };

void jvp::NetworkMount::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    auto *_t = static_cast<NetworkMount *>(_o);
    if (_c == QMetaObject::InvokeMetaMethod) {
        switch (_id) {
        case 0: _t->passwordRequested((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[2])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[3])),(*reinterpret_cast<std::add_pointer_t<int>>(_a[4]))); break;
        case 1: _t->questionAsked((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<QStringList>>(_a[2]))); break;
        case 2: _t->finished((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[2])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[3]))); break;
        case 3: _t->reply((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[2])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[3])),(*reinterpret_cast<std::add_pointer_t<bool>>(_a[4]))); break;
        case 4: _t->answer((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 5: _t->cancel(); break;
        default: ;
        }
    }
    if (_c == QMetaObject::IndexOfMethod) {
        if (QtMocHelpers::indexOfMethod<void (NetworkMount::*)(const QString & , const QString & , const QString & , int )>(_a, &NetworkMount::passwordRequested, 0))
            return;
        if (QtMocHelpers::indexOfMethod<void (NetworkMount::*)(const QString & , const QStringList & )>(_a, &NetworkMount::questionAsked, 1))
            return;
        if (QtMocHelpers::indexOfMethod<void (NetworkMount::*)(const QString & , const QString & , const QString & )>(_a, &NetworkMount::finished, 2))
            return;
    }
}

const QMetaObject *jvp::NetworkMount::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *jvp::NetworkMount::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp12NetworkMountE_t>.strings))
        return static_cast<void*>(this);
    return QObject::qt_metacast(_clname);
}

int jvp::NetworkMount::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QObject::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 6)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 6;
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 6)
            *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType();
        _id -= 6;
    }
    return _id;
}

// SIGNAL 0
void jvp::NetworkMount::passwordRequested(const QString & _t1, const QString & _t2, const QString & _t3, int _t4)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 0, nullptr, _t1, _t2, _t3, _t4);
}

// SIGNAL 1
void jvp::NetworkMount::questionAsked(const QString & _t1, const QStringList & _t2)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 1, nullptr, _t1, _t2);
}

// SIGNAL 2
void jvp::NetworkMount::finished(const QString & _t1, const QString & _t2, const QString & _t3)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 2, nullptr, _t1, _t2, _t3);
}
QT_WARNING_POP
