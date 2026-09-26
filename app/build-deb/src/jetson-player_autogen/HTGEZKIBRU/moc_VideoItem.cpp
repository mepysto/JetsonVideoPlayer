/****************************************************************************
** Meta object code from reading C++ file 'VideoItem.h'
**
** Created by: The Qt Meta Object Compiler version 69 (Qt 6.11.3)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include "../../../../src/media/VideoItem.h"
#include <QtCore/qmetatype.h>

#include <QtCore/qtmochelpers.h>

#include <memory>


#include <QtCore/qxptype_traits.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'VideoItem.h' doesn't include <QObject>."
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
struct qt_meta_tag_ZN3jvp9VideoItemE_t {};
} // unnamed namespace

template <> constexpr inline auto jvp::VideoItem::qt_create_metaobjectdata<qt_meta_tag_ZN3jvp9VideoItemE_t>()
{
    namespace QMC = QtMocConstants;
    QtMocHelpers::StringRefStorage qt_stringData {
        "jvp::VideoItem",
        "QML.Element",
        "auto",
        "bridgeChanged",
        "",
        "hdrChanged",
        "orientationChanged",
        "videoRectChanged",
        "bridge",
        "hdrMode",
        "hdrMatrixFix",
        "orientation",
        "videoRect",
        "QRectF",
        "videoSize",
        "QSizeF"
    };

    QtMocHelpers::UintData qt_methods {
        // Signal 'bridgeChanged'
        QtMocHelpers::SignalData<void()>(3, 4, QMC::AccessPublic, QMetaType::Void),
        // Signal 'hdrChanged'
        QtMocHelpers::SignalData<void()>(5, 4, QMC::AccessPublic, QMetaType::Void),
        // Signal 'orientationChanged'
        QtMocHelpers::SignalData<void()>(6, 4, QMC::AccessPublic, QMetaType::Void),
        // Signal 'videoRectChanged'
        QtMocHelpers::SignalData<void()>(7, 4, QMC::AccessPublic, QMetaType::Void),
    };
    QtMocHelpers::UintData qt_properties {
        // property 'bridge'
        QtMocHelpers::PropertyData<QObject*>(8, QMetaType::QObjectStar, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet, 0),
        // property 'hdrMode'
        QtMocHelpers::PropertyData<int>(9, QMetaType::Int, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet, 1),
        // property 'hdrMatrixFix'
        QtMocHelpers::PropertyData<bool>(10, QMetaType::Bool, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet, 1),
        // property 'orientation'
        QtMocHelpers::PropertyData<QString>(11, QMetaType::QString, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet, 2),
        // property 'videoRect'
        QtMocHelpers::PropertyData<QRectF>(12, 0x80000000 | 13, QMC::DefaultPropertyFlags | QMC::EnumOrFlag, 3),
        // property 'videoSize'
        QtMocHelpers::PropertyData<QSizeF>(14, 0x80000000 | 15, QMC::DefaultPropertyFlags | QMC::EnumOrFlag, 3),
    };
    QtMocHelpers::UintData qt_enums {
    };
    QtMocHelpers::UintData qt_constructors {};
    QtMocHelpers::ClassInfos qt_classinfo({
            {    1,    2 },
    });
    return QtMocHelpers::metaObjectData<VideoItem, void>(QMC::MetaObjectFlag{}, qt_stringData,
            qt_methods, qt_properties, qt_enums, qt_constructors, qt_classinfo);
}
Q_CONSTINIT const QMetaObject jvp::VideoItem::staticMetaObject = { {
    QMetaObject::SuperData::link<QQuickItem::staticMetaObject>(),
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp9VideoItemE_t>.stringdata,
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp9VideoItemE_t>.data,
    qt_static_metacall,
    nullptr,
    qt_staticMetaObjectRelocatingContent<qt_meta_tag_ZN3jvp9VideoItemE_t>.metaTypes,
    nullptr
} };

void jvp::VideoItem::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    auto *_t = static_cast<VideoItem *>(_o);
    if (_c == QMetaObject::InvokeMetaMethod) {
        switch (_id) {
        case 0: _t->bridgeChanged(); break;
        case 1: _t->hdrChanged(); break;
        case 2: _t->orientationChanged(); break;
        case 3: _t->videoRectChanged(); break;
        default: ;
        }
    }
    if (_c == QMetaObject::IndexOfMethod) {
        if (QtMocHelpers::indexOfMethod<void (VideoItem::*)()>(_a, &VideoItem::bridgeChanged, 0))
            return;
        if (QtMocHelpers::indexOfMethod<void (VideoItem::*)()>(_a, &VideoItem::hdrChanged, 1))
            return;
        if (QtMocHelpers::indexOfMethod<void (VideoItem::*)()>(_a, &VideoItem::orientationChanged, 2))
            return;
        if (QtMocHelpers::indexOfMethod<void (VideoItem::*)()>(_a, &VideoItem::videoRectChanged, 3))
            return;
    }
    if (_c == QMetaObject::ReadProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 0: *reinterpret_cast<QObject**>(_v) = _t->bridge(); break;
        case 1: *reinterpret_cast<int*>(_v) = _t->hdrMode(); break;
        case 2: *reinterpret_cast<bool*>(_v) = _t->hdrMatrixFix(); break;
        case 3: *reinterpret_cast<QString*>(_v) = _t->orientation(); break;
        case 4: *reinterpret_cast<QRectF*>(_v) = _t->videoRect(); break;
        case 5: *reinterpret_cast<QSizeF*>(_v) = _t->videoSize(); break;
        default: break;
        }
    }
    if (_c == QMetaObject::WriteProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 0: _t->setBridge(*reinterpret_cast<QObject**>(_v)); break;
        case 1: _t->setHdrMode(*reinterpret_cast<int*>(_v)); break;
        case 2: _t->setHdrMatrixFix(*reinterpret_cast<bool*>(_v)); break;
        case 3: _t->setOrientation(*reinterpret_cast<QString*>(_v)); break;
        default: break;
        }
    }
}

const QMetaObject *jvp::VideoItem::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *jvp::VideoItem::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp9VideoItemE_t>.strings))
        return static_cast<void*>(this);
    return QQuickItem::qt_metacast(_clname);
}

int jvp::VideoItem::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QQuickItem::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 4)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 4;
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 4)
            *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType();
        _id -= 4;
    }
    if (_c == QMetaObject::ReadProperty || _c == QMetaObject::WriteProperty
            || _c == QMetaObject::ResetProperty || _c == QMetaObject::BindableProperty
            || _c == QMetaObject::RegisterPropertyMetaType) {
        qt_static_metacall(this, _c, _id, _a);
        _id -= 6;
    }
    return _id;
}

// SIGNAL 0
void jvp::VideoItem::bridgeChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 0, nullptr);
}

// SIGNAL 1
void jvp::VideoItem::hdrChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 1, nullptr);
}

// SIGNAL 2
void jvp::VideoItem::orientationChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 2, nullptr);
}

// SIGNAL 3
void jvp::VideoItem::videoRectChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 3, nullptr);
}
QT_WARNING_POP
