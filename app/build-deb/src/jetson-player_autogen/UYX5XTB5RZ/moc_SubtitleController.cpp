/****************************************************************************
** Meta object code from reading C++ file 'SubtitleController.h'
**
** Created by: The Qt Meta Object Compiler version 69 (Qt 6.11.3)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include "../../../../src/ui/SubtitleController.h"
#include <QtCore/qmetatype.h>

#include <QtCore/qtmochelpers.h>

#include <memory>


#include <QtCore/qxptype_traits.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'SubtitleController.h' doesn't include <QObject>."
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
struct qt_meta_tag_ZN3jvp18SubtitleControllerE_t {};
} // unnamed namespace

template <> constexpr inline auto jvp::SubtitleController::qt_create_metaobjectdata<qt_meta_tag_ZN3jvp18SubtitleControllerE_t>()
{
    namespace QMC = QtMocConstants;
    QtMocHelpers::StringRefStorage qt_stringData {
        "jvp::SubtitleController",
        "QML.Element",
        "anonymous",
        "changed",
        "",
        "osd",
        "text",
        "popupRequested",
        "embeddedTrackRequested",
        "index",
        "fontScaleChanged",
        "scale",
        "toggle",
        "buttonClicked",
        "toggleTrack",
        "toggleEmbedded",
        "cycleEmbeddedTrack",
        "adjustScale",
        "delta",
        "resetScale",
        "adjustSync",
        "deltaMs",
        "resetSync",
        "tracks",
        "QVariantList",
        "enabled",
        "embeddedCount",
        "embeddedEnabled",
        "embeddedLabel",
        "fontScale",
        "offsetMs",
        "buttonText"
    };

    QtMocHelpers::UintData qt_methods {
        // Signal 'changed'
        QtMocHelpers::SignalData<void()>(3, 4, QMC::AccessPublic, QMetaType::Void),
        // Signal 'osd'
        QtMocHelpers::SignalData<void(const QString &)>(5, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 6 },
        }}),
        // Signal 'popupRequested'
        QtMocHelpers::SignalData<void()>(7, 4, QMC::AccessPublic, QMetaType::Void),
        // Signal 'embeddedTrackRequested'
        QtMocHelpers::SignalData<void(int)>(8, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 9 },
        }}),
        // Signal 'fontScaleChanged'
        QtMocHelpers::SignalData<void(double)>(10, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 11 },
        }}),
        // Method 'toggle'
        QtMocHelpers::MethodData<void()>(12, 4, QMC::AccessPublic, QMetaType::Void),
        // Method 'buttonClicked'
        QtMocHelpers::MethodData<void()>(13, 4, QMC::AccessPublic, QMetaType::Void),
        // Method 'toggleTrack'
        QtMocHelpers::MethodData<void(int)>(14, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 9 },
        }}),
        // Method 'toggleEmbedded'
        QtMocHelpers::MethodData<void()>(15, 4, QMC::AccessPublic, QMetaType::Void),
        // Method 'cycleEmbeddedTrack'
        QtMocHelpers::MethodData<void()>(16, 4, QMC::AccessPublic, QMetaType::Void),
        // Method 'adjustScale'
        QtMocHelpers::MethodData<void(double)>(17, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 18 },
        }}),
        // Method 'resetScale'
        QtMocHelpers::MethodData<void()>(19, 4, QMC::AccessPublic, QMetaType::Void),
        // Method 'adjustSync'
        QtMocHelpers::MethodData<void(int)>(20, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 21 },
        }}),
        // Method 'resetSync'
        QtMocHelpers::MethodData<void()>(22, 4, QMC::AccessPublic, QMetaType::Void),
    };
    QtMocHelpers::UintData qt_properties {
        // property 'tracks'
        QtMocHelpers::PropertyData<QVariantList>(23, 0x80000000 | 24, QMC::DefaultPropertyFlags | QMC::EnumOrFlag, 0),
        // property 'enabled'
        QtMocHelpers::PropertyData<bool>(25, QMetaType::Bool, QMC::DefaultPropertyFlags, 0),
        // property 'embeddedCount'
        QtMocHelpers::PropertyData<int>(26, QMetaType::Int, QMC::DefaultPropertyFlags, 0),
        // property 'embeddedEnabled'
        QtMocHelpers::PropertyData<bool>(27, QMetaType::Bool, QMC::DefaultPropertyFlags, 0),
        // property 'embeddedLabel'
        QtMocHelpers::PropertyData<QString>(28, QMetaType::QString, QMC::DefaultPropertyFlags, 0),
        // property 'fontScale'
        QtMocHelpers::PropertyData<double>(29, QMetaType::Double, QMC::DefaultPropertyFlags, 0),
        // property 'offsetMs'
        QtMocHelpers::PropertyData<int>(30, QMetaType::Int, QMC::DefaultPropertyFlags, 0),
        // property 'buttonText'
        QtMocHelpers::PropertyData<QString>(31, QMetaType::QString, QMC::DefaultPropertyFlags, 0),
    };
    QtMocHelpers::UintData qt_enums {
    };
    QtMocHelpers::UintData qt_constructors {};
    QtMocHelpers::ClassInfos qt_classinfo({
            {    1,    2 },
    });
    return QtMocHelpers::metaObjectData<SubtitleController, void>(QMC::MetaObjectFlag{}, qt_stringData,
            qt_methods, qt_properties, qt_enums, qt_constructors, qt_classinfo);
}
Q_CONSTINIT const QMetaObject jvp::SubtitleController::staticMetaObject = { {
    QMetaObject::SuperData::link<QObject::staticMetaObject>(),
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp18SubtitleControllerE_t>.stringdata,
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp18SubtitleControllerE_t>.data,
    qt_static_metacall,
    nullptr,
    qt_staticMetaObjectRelocatingContent<qt_meta_tag_ZN3jvp18SubtitleControllerE_t>.metaTypes,
    nullptr
} };

void jvp::SubtitleController::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    auto *_t = static_cast<SubtitleController *>(_o);
    if (_c == QMetaObject::InvokeMetaMethod) {
        switch (_id) {
        case 0: _t->changed(); break;
        case 1: _t->osd((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 2: _t->popupRequested(); break;
        case 3: _t->embeddedTrackRequested((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 4: _t->fontScaleChanged((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 5: _t->toggle(); break;
        case 6: _t->buttonClicked(); break;
        case 7: _t->toggleTrack((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 8: _t->toggleEmbedded(); break;
        case 9: _t->cycleEmbeddedTrack(); break;
        case 10: _t->adjustScale((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 11: _t->resetScale(); break;
        case 12: _t->adjustSync((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 13: _t->resetSync(); break;
        default: ;
        }
    }
    if (_c == QMetaObject::IndexOfMethod) {
        if (QtMocHelpers::indexOfMethod<void (SubtitleController::*)()>(_a, &SubtitleController::changed, 0))
            return;
        if (QtMocHelpers::indexOfMethod<void (SubtitleController::*)(const QString & )>(_a, &SubtitleController::osd, 1))
            return;
        if (QtMocHelpers::indexOfMethod<void (SubtitleController::*)()>(_a, &SubtitleController::popupRequested, 2))
            return;
        if (QtMocHelpers::indexOfMethod<void (SubtitleController::*)(int )>(_a, &SubtitleController::embeddedTrackRequested, 3))
            return;
        if (QtMocHelpers::indexOfMethod<void (SubtitleController::*)(double )>(_a, &SubtitleController::fontScaleChanged, 4))
            return;
    }
    if (_c == QMetaObject::ReadProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 0: *reinterpret_cast<QVariantList*>(_v) = _t->tracksForQml(); break;
        case 1: *reinterpret_cast<bool*>(_v) = _t->enabled(); break;
        case 2: *reinterpret_cast<int*>(_v) = _t->embeddedCount(); break;
        case 3: *reinterpret_cast<bool*>(_v) = _t->embeddedEnabled(); break;
        case 4: *reinterpret_cast<QString*>(_v) = _t->embeddedLabel(); break;
        case 5: *reinterpret_cast<double*>(_v) = _t->fontScale(); break;
        case 6: *reinterpret_cast<int*>(_v) = _t->offsetMs(); break;
        case 7: *reinterpret_cast<QString*>(_v) = _t->buttonText(); break;
        default: break;
        }
    }
}

const QMetaObject *jvp::SubtitleController::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *jvp::SubtitleController::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp18SubtitleControllerE_t>.strings))
        return static_cast<void*>(this);
    return QObject::qt_metacast(_clname);
}

int jvp::SubtitleController::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QObject::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 14)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 14;
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 14)
            *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType();
        _id -= 14;
    }
    if (_c == QMetaObject::ReadProperty || _c == QMetaObject::WriteProperty
            || _c == QMetaObject::ResetProperty || _c == QMetaObject::BindableProperty
            || _c == QMetaObject::RegisterPropertyMetaType) {
        qt_static_metacall(this, _c, _id, _a);
        _id -= 8;
    }
    return _id;
}

// SIGNAL 0
void jvp::SubtitleController::changed()
{
    QMetaObject::activate(this, &staticMetaObject, 0, nullptr);
}

// SIGNAL 1
void jvp::SubtitleController::osd(const QString & _t1)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 1, nullptr, _t1);
}

// SIGNAL 2
void jvp::SubtitleController::popupRequested()
{
    QMetaObject::activate(this, &staticMetaObject, 2, nullptr);
}

// SIGNAL 3
void jvp::SubtitleController::embeddedTrackRequested(int _t1)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 3, nullptr, _t1);
}

// SIGNAL 4
void jvp::SubtitleController::fontScaleChanged(double _t1)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 4, nullptr, _t1);
}
QT_WARNING_POP
