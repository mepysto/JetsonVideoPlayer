/****************************************************************************
** Meta object code from reading C++ file 'Mpris.h'
**
** Created by: The Qt Meta Object Compiler version 69 (Qt 6.11.3)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include "../../../../src/services/Mpris.h"
#include <QtCore/qmetatype.h>

#include <QtCore/qtmochelpers.h>

#include <memory>


#include <QtCore/qxptype_traits.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'Mpris.h' doesn't include <QObject>."
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
struct qt_meta_tag_ZN3jvp12MprisServiceE_t {};
} // unnamed namespace

template <> constexpr inline auto jvp::MprisService::qt_create_metaobjectdata<qt_meta_tag_ZN3jvp12MprisServiceE_t>()
{
    namespace QMC = QtMocConstants;
    QtMocHelpers::StringRefStorage qt_stringData {
        "jvp::MprisService",
        "seeked",
        "",
        "positionUs"
    };

    QtMocHelpers::UintData qt_methods {
        // Signal 'seeked'
        QtMocHelpers::SignalData<void(qlonglong)>(1, 2, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::LongLong, 3 },
        }}),
    };
    QtMocHelpers::UintData qt_properties {
    };
    QtMocHelpers::UintData qt_enums {
    };
    return QtMocHelpers::metaObjectData<MprisService, qt_meta_tag_ZN3jvp12MprisServiceE_t>(QMC::MetaObjectFlag{}, qt_stringData,
            qt_methods, qt_properties, qt_enums);
}
Q_CONSTINIT const QMetaObject jvp::MprisService::staticMetaObject = { {
    QMetaObject::SuperData::link<QObject::staticMetaObject>(),
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp12MprisServiceE_t>.stringdata,
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp12MprisServiceE_t>.data,
    qt_static_metacall,
    nullptr,
    qt_staticMetaObjectRelocatingContent<qt_meta_tag_ZN3jvp12MprisServiceE_t>.metaTypes,
    nullptr
} };

void jvp::MprisService::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    auto *_t = static_cast<MprisService *>(_o);
    if (_c == QMetaObject::InvokeMetaMethod) {
        switch (_id) {
        case 0: _t->seeked((*reinterpret_cast<std::add_pointer_t<qlonglong>>(_a[1]))); break;
        default: ;
        }
    }
    if (_c == QMetaObject::IndexOfMethod) {
        if (QtMocHelpers::indexOfMethod<void (MprisService::*)(qlonglong )>(_a, &MprisService::seeked, 0))
            return;
    }
}

const QMetaObject *jvp::MprisService::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *jvp::MprisService::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp12MprisServiceE_t>.strings))
        return static_cast<void*>(this);
    return QObject::qt_metacast(_clname);
}

int jvp::MprisService::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QObject::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 1)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 1;
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 1)
            *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType();
        _id -= 1;
    }
    return _id;
}

// SIGNAL 0
void jvp::MprisService::seeked(qlonglong _t1)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 0, nullptr, _t1);
}
namespace {
struct qt_meta_tag_ZN3jvp6detail16MprisRootAdaptorE_t {};
} // unnamed namespace

template <> constexpr inline auto jvp::detail::MprisRootAdaptor::qt_create_metaobjectdata<qt_meta_tag_ZN3jvp6detail16MprisRootAdaptorE_t>()
{
    namespace QMC = QtMocConstants;
    QtMocHelpers::StringRefStorage qt_stringData {
        "jvp::detail::MprisRootAdaptor",
        "D-Bus Interface",
        "org.mpris.MediaPlayer2",
        "Raise",
        "",
        "Quit",
        "CanQuit",
        "CanRaise",
        "CanSetFullscreen",
        "Fullscreen",
        "HasTrackList",
        "Identity",
        "DesktopEntry",
        "SupportedUriSchemes",
        "SupportedMimeTypes"
    };

    QtMocHelpers::UintData qt_methods {
        // Slot 'Raise'
        QtMocHelpers::SlotData<void()>(3, 4, QMC::AccessPublic, QMetaType::Void),
        // Slot 'Quit'
        QtMocHelpers::SlotData<void()>(5, 4, QMC::AccessPublic, QMetaType::Void),
    };
    QtMocHelpers::UintData qt_properties {
        // property 'CanQuit'
        QtMocHelpers::PropertyData<bool>(6, QMetaType::Bool, QMC::DefaultPropertyFlags),
        // property 'CanRaise'
        QtMocHelpers::PropertyData<bool>(7, QMetaType::Bool, QMC::DefaultPropertyFlags),
        // property 'CanSetFullscreen'
        QtMocHelpers::PropertyData<bool>(8, QMetaType::Bool, QMC::DefaultPropertyFlags),
        // property 'Fullscreen'
        QtMocHelpers::PropertyData<bool>(9, QMetaType::Bool, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet),
        // property 'HasTrackList'
        QtMocHelpers::PropertyData<bool>(10, QMetaType::Bool, QMC::DefaultPropertyFlags),
        // property 'Identity'
        QtMocHelpers::PropertyData<QString>(11, QMetaType::QString, QMC::DefaultPropertyFlags),
        // property 'DesktopEntry'
        QtMocHelpers::PropertyData<QString>(12, QMetaType::QString, QMC::DefaultPropertyFlags),
        // property 'SupportedUriSchemes'
        QtMocHelpers::PropertyData<QStringList>(13, QMetaType::QStringList, QMC::DefaultPropertyFlags),
        // property 'SupportedMimeTypes'
        QtMocHelpers::PropertyData<QStringList>(14, QMetaType::QStringList, QMC::DefaultPropertyFlags),
    };
    QtMocHelpers::UintData qt_enums {
    };
    QtMocHelpers::UintData qt_constructors {};
    QtMocHelpers::ClassInfos qt_classinfo({
            {    1,    2 },
    });
    return QtMocHelpers::metaObjectData<MprisRootAdaptor, qt_meta_tag_ZN3jvp6detail16MprisRootAdaptorE_t>(QMC::MetaObjectFlag{}, qt_stringData,
            qt_methods, qt_properties, qt_enums, qt_constructors, qt_classinfo);
}
Q_CONSTINIT const QMetaObject jvp::detail::MprisRootAdaptor::staticMetaObject = { {
    QMetaObject::SuperData::link<QDBusAbstractAdaptor::staticMetaObject>(),
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp6detail16MprisRootAdaptorE_t>.stringdata,
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp6detail16MprisRootAdaptorE_t>.data,
    qt_static_metacall,
    nullptr,
    qt_staticMetaObjectRelocatingContent<qt_meta_tag_ZN3jvp6detail16MprisRootAdaptorE_t>.metaTypes,
    nullptr
} };

void jvp::detail::MprisRootAdaptor::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    auto *_t = static_cast<MprisRootAdaptor *>(_o);
    if (_c == QMetaObject::InvokeMetaMethod) {
        switch (_id) {
        case 0: _t->Raise(); break;
        case 1: _t->Quit(); break;
        default: ;
        }
    }
    if (_c == QMetaObject::ReadProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 0: *reinterpret_cast<bool*>(_v) = _t->canQuit(); break;
        case 1: *reinterpret_cast<bool*>(_v) = _t->canRaise(); break;
        case 2: *reinterpret_cast<bool*>(_v) = _t->canSetFullscreen(); break;
        case 3: *reinterpret_cast<bool*>(_v) = _t->fullscreen(); break;
        case 4: *reinterpret_cast<bool*>(_v) = _t->hasTrackList(); break;
        case 5: *reinterpret_cast<QString*>(_v) = _t->identity(); break;
        case 6: *reinterpret_cast<QString*>(_v) = _t->desktopEntry(); break;
        case 7: *reinterpret_cast<QStringList*>(_v) = _t->supportedUriSchemes(); break;
        case 8: *reinterpret_cast<QStringList*>(_v) = _t->supportedMimeTypes(); break;
        default: break;
        }
    }
    if (_c == QMetaObject::WriteProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 3: _t->setFullscreen(*reinterpret_cast<bool*>(_v)); break;
        default: break;
        }
    }
}

const QMetaObject *jvp::detail::MprisRootAdaptor::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *jvp::detail::MprisRootAdaptor::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp6detail16MprisRootAdaptorE_t>.strings))
        return static_cast<void*>(this);
    return QDBusAbstractAdaptor::qt_metacast(_clname);
}

int jvp::detail::MprisRootAdaptor::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QDBusAbstractAdaptor::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 2)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 2;
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 2)
            *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType();
        _id -= 2;
    }
    if (_c == QMetaObject::ReadProperty || _c == QMetaObject::WriteProperty
            || _c == QMetaObject::ResetProperty || _c == QMetaObject::BindableProperty
            || _c == QMetaObject::RegisterPropertyMetaType) {
        qt_static_metacall(this, _c, _id, _a);
        _id -= 9;
    }
    return _id;
}
namespace {
struct qt_meta_tag_ZN3jvp6detail18MprisPlayerAdaptorE_t {};
} // unnamed namespace

template <> constexpr inline auto jvp::detail::MprisPlayerAdaptor::qt_create_metaobjectdata<qt_meta_tag_ZN3jvp6detail18MprisPlayerAdaptorE_t>()
{
    namespace QMC = QtMocConstants;
    QtMocHelpers::StringRefStorage qt_stringData {
        "jvp::detail::MprisPlayerAdaptor",
        "D-Bus Interface",
        "org.mpris.MediaPlayer2.Player",
        "Seeked",
        "",
        "position",
        "Next",
        "Previous",
        "Pause",
        "PlayPause",
        "Stop",
        "Play",
        "Seek",
        "offset",
        "SetPosition",
        "QDBusObjectPath",
        "trackId",
        "OpenUri",
        "uri",
        "PlaybackStatus",
        "LoopStatus",
        "Rate",
        "Shuffle",
        "Metadata",
        "QVariantMap",
        "Volume",
        "Position",
        "MinimumRate",
        "MaximumRate",
        "CanGoNext",
        "CanGoPrevious",
        "CanPlay",
        "CanPause",
        "CanSeek",
        "CanControl"
    };

    QtMocHelpers::UintData qt_methods {
        // Signal 'Seeked'
        QtMocHelpers::SignalData<void(qlonglong)>(3, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::LongLong, 5 },
        }}),
        // Slot 'Next'
        QtMocHelpers::SlotData<void()>(6, 4, QMC::AccessPublic, QMetaType::Void),
        // Slot 'Previous'
        QtMocHelpers::SlotData<void()>(7, 4, QMC::AccessPublic, QMetaType::Void),
        // Slot 'Pause'
        QtMocHelpers::SlotData<void()>(8, 4, QMC::AccessPublic, QMetaType::Void),
        // Slot 'PlayPause'
        QtMocHelpers::SlotData<void()>(9, 4, QMC::AccessPublic, QMetaType::Void),
        // Slot 'Stop'
        QtMocHelpers::SlotData<void()>(10, 4, QMC::AccessPublic, QMetaType::Void),
        // Slot 'Play'
        QtMocHelpers::SlotData<void()>(11, 4, QMC::AccessPublic, QMetaType::Void),
        // Slot 'Seek'
        QtMocHelpers::SlotData<void(qlonglong)>(12, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::LongLong, 13 },
        }}),
        // Slot 'SetPosition'
        QtMocHelpers::SlotData<void(const QDBusObjectPath &, qlonglong)>(14, 4, QMC::AccessPublic, QMetaType::Void, {{
            { 0x80000000 | 15, 16 }, { QMetaType::LongLong, 5 },
        }}),
        // Slot 'OpenUri'
        QtMocHelpers::SlotData<void(const QString &)>(17, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 18 },
        }}),
    };
    QtMocHelpers::UintData qt_properties {
        // property 'PlaybackStatus'
        QtMocHelpers::PropertyData<QString>(19, QMetaType::QString, QMC::DefaultPropertyFlags),
        // property 'LoopStatus'
        QtMocHelpers::PropertyData<QString>(20, QMetaType::QString, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet),
        // property 'Rate'
        QtMocHelpers::PropertyData<double>(21, QMetaType::Double, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet),
        // property 'Shuffle'
        QtMocHelpers::PropertyData<bool>(22, QMetaType::Bool, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet),
        // property 'Metadata'
        QtMocHelpers::PropertyData<QVariantMap>(23, 0x80000000 | 24, QMC::DefaultPropertyFlags | QMC::EnumOrFlag),
        // property 'Volume'
        QtMocHelpers::PropertyData<double>(25, QMetaType::Double, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet),
        // property 'Position'
        QtMocHelpers::PropertyData<qlonglong>(26, QMetaType::LongLong, QMC::DefaultPropertyFlags),
        // property 'MinimumRate'
        QtMocHelpers::PropertyData<double>(27, QMetaType::Double, QMC::DefaultPropertyFlags),
        // property 'MaximumRate'
        QtMocHelpers::PropertyData<double>(28, QMetaType::Double, QMC::DefaultPropertyFlags),
        // property 'CanGoNext'
        QtMocHelpers::PropertyData<bool>(29, QMetaType::Bool, QMC::DefaultPropertyFlags),
        // property 'CanGoPrevious'
        QtMocHelpers::PropertyData<bool>(30, QMetaType::Bool, QMC::DefaultPropertyFlags),
        // property 'CanPlay'
        QtMocHelpers::PropertyData<bool>(31, QMetaType::Bool, QMC::DefaultPropertyFlags),
        // property 'CanPause'
        QtMocHelpers::PropertyData<bool>(32, QMetaType::Bool, QMC::DefaultPropertyFlags),
        // property 'CanSeek'
        QtMocHelpers::PropertyData<bool>(33, QMetaType::Bool, QMC::DefaultPropertyFlags),
        // property 'CanControl'
        QtMocHelpers::PropertyData<bool>(34, QMetaType::Bool, QMC::DefaultPropertyFlags),
    };
    QtMocHelpers::UintData qt_enums {
    };
    QtMocHelpers::UintData qt_constructors {};
    QtMocHelpers::ClassInfos qt_classinfo({
            {    1,    2 },
    });
    return QtMocHelpers::metaObjectData<MprisPlayerAdaptor, qt_meta_tag_ZN3jvp6detail18MprisPlayerAdaptorE_t>(QMC::MetaObjectFlag{}, qt_stringData,
            qt_methods, qt_properties, qt_enums, qt_constructors, qt_classinfo);
}
Q_CONSTINIT const QMetaObject jvp::detail::MprisPlayerAdaptor::staticMetaObject = { {
    QMetaObject::SuperData::link<QDBusAbstractAdaptor::staticMetaObject>(),
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp6detail18MprisPlayerAdaptorE_t>.stringdata,
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp6detail18MprisPlayerAdaptorE_t>.data,
    qt_static_metacall,
    nullptr,
    qt_staticMetaObjectRelocatingContent<qt_meta_tag_ZN3jvp6detail18MprisPlayerAdaptorE_t>.metaTypes,
    nullptr
} };

void jvp::detail::MprisPlayerAdaptor::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    auto *_t = static_cast<MprisPlayerAdaptor *>(_o);
    if (_c == QMetaObject::InvokeMetaMethod) {
        switch (_id) {
        case 0: _t->Seeked((*reinterpret_cast<std::add_pointer_t<qlonglong>>(_a[1]))); break;
        case 1: _t->Next(); break;
        case 2: _t->Previous(); break;
        case 3: _t->Pause(); break;
        case 4: _t->PlayPause(); break;
        case 5: _t->Stop(); break;
        case 6: _t->Play(); break;
        case 7: _t->Seek((*reinterpret_cast<std::add_pointer_t<qlonglong>>(_a[1]))); break;
        case 8: _t->SetPosition((*reinterpret_cast<std::add_pointer_t<QDBusObjectPath>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<qlonglong>>(_a[2]))); break;
        case 9: _t->OpenUri((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        default: ;
        }
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        switch (_id) {
        default: *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType(); break;
        case 8:
            switch (*reinterpret_cast<int*>(_a[1])) {
            default: *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType(); break;
            case 0:
                *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType::fromType< QDBusObjectPath >(); break;
            }
            break;
        }
    }
    if (_c == QMetaObject::IndexOfMethod) {
        if (QtMocHelpers::indexOfMethod<void (MprisPlayerAdaptor::*)(qlonglong )>(_a, &MprisPlayerAdaptor::Seeked, 0))
            return;
    }
    if (_c == QMetaObject::ReadProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 0: *reinterpret_cast<QString*>(_v) = _t->playbackStatus(); break;
        case 1: *reinterpret_cast<QString*>(_v) = _t->loopStatus(); break;
        case 2: *reinterpret_cast<double*>(_v) = _t->rate(); break;
        case 3: *reinterpret_cast<bool*>(_v) = _t->shuffle(); break;
        case 4: *reinterpret_cast<QVariantMap*>(_v) = _t->metadata(); break;
        case 5: *reinterpret_cast<double*>(_v) = _t->volume(); break;
        case 6: *reinterpret_cast<qlonglong*>(_v) = _t->position(); break;
        case 7: *reinterpret_cast<double*>(_v) = _t->minimumRate(); break;
        case 8: *reinterpret_cast<double*>(_v) = _t->maximumRate(); break;
        case 9: *reinterpret_cast<bool*>(_v) = _t->canGoNext(); break;
        case 10: *reinterpret_cast<bool*>(_v) = _t->canGoPrevious(); break;
        case 11: *reinterpret_cast<bool*>(_v) = _t->canPlay(); break;
        case 12: *reinterpret_cast<bool*>(_v) = _t->canPause(); break;
        case 13: *reinterpret_cast<bool*>(_v) = _t->canSeek(); break;
        case 14: *reinterpret_cast<bool*>(_v) = _t->canControl(); break;
        default: break;
        }
    }
    if (_c == QMetaObject::WriteProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 1: _t->setLoopStatus(*reinterpret_cast<QString*>(_v)); break;
        case 2: _t->setRate(*reinterpret_cast<double*>(_v)); break;
        case 3: _t->setShuffle(*reinterpret_cast<bool*>(_v)); break;
        case 5: _t->setVolume(*reinterpret_cast<double*>(_v)); break;
        default: break;
        }
    }
}

const QMetaObject *jvp::detail::MprisPlayerAdaptor::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *jvp::detail::MprisPlayerAdaptor::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp6detail18MprisPlayerAdaptorE_t>.strings))
        return static_cast<void*>(this);
    return QDBusAbstractAdaptor::qt_metacast(_clname);
}

int jvp::detail::MprisPlayerAdaptor::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QDBusAbstractAdaptor::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 10)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 10;
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 10)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 10;
    }
    if (_c == QMetaObject::ReadProperty || _c == QMetaObject::WriteProperty
            || _c == QMetaObject::ResetProperty || _c == QMetaObject::BindableProperty
            || _c == QMetaObject::RegisterPropertyMetaType) {
        qt_static_metacall(this, _c, _id, _a);
        _id -= 15;
    }
    return _id;
}

// SIGNAL 0
void jvp::detail::MprisPlayerAdaptor::Seeked(qlonglong _t1)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 0, nullptr, _t1);
}
QT_WARNING_POP
