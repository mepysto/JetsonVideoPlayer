/****************************************************************************
** Meta object code from reading C++ file 'PlaylistModel.h'
**
** Created by: The Qt Meta Object Compiler version 69 (Qt 6.11.3)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include "../../../../src/ui/PlaylistModel.h"
#include <QtCore/qmetatype.h>

#include <QtCore/qtmochelpers.h>

#include <memory>


#include <QtCore/qxptype_traits.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'PlaylistModel.h' doesn't include <QObject>."
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
struct qt_meta_tag_ZN3jvp13PlaylistModelE_t {};
} // unnamed namespace

template <> constexpr inline auto jvp::PlaylistModel::qt_create_metaobjectdata<qt_meta_tag_ZN3jvp13PlaylistModelE_t>()
{
    namespace QMC = QtMocConstants;
    QtMocHelpers::StringRefStorage qt_stringData {
        "jvp::PlaylistModel",
        "QML.Element",
        "anonymous",
        "countChanged",
        "",
        "filterChanged",
        "activeRowChanged",
        "sortLabelChanged",
        "playRequested",
        "playlistIndex",
        "sortCycleRequested",
        "toggleExpanded",
        "row",
        "expandAll",
        "collapseAll",
        "playFirstMatch",
        "cycleSort",
        "count",
        "filter",
        "activeRow",
        "sortLabel"
    };

    QtMocHelpers::UintData qt_methods {
        // Signal 'countChanged'
        QtMocHelpers::SignalData<void()>(3, 4, QMC::AccessPublic, QMetaType::Void),
        // Signal 'filterChanged'
        QtMocHelpers::SignalData<void()>(5, 4, QMC::AccessPublic, QMetaType::Void),
        // Signal 'activeRowChanged'
        QtMocHelpers::SignalData<void()>(6, 4, QMC::AccessPublic, QMetaType::Void),
        // Signal 'sortLabelChanged'
        QtMocHelpers::SignalData<void()>(7, 4, QMC::AccessPublic, QMetaType::Void),
        // Signal 'playRequested'
        QtMocHelpers::SignalData<void(int)>(8, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 9 },
        }}),
        // Signal 'sortCycleRequested'
        QtMocHelpers::SignalData<void()>(10, 4, QMC::AccessPublic, QMetaType::Void),
        // Method 'toggleExpanded'
        QtMocHelpers::MethodData<void(int)>(11, 4, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 12 },
        }}),
        // Method 'expandAll'
        QtMocHelpers::MethodData<void()>(13, 4, QMC::AccessPublic, QMetaType::Void),
        // Method 'collapseAll'
        QtMocHelpers::MethodData<void()>(14, 4, QMC::AccessPublic, QMetaType::Void),
        // Method 'playFirstMatch'
        QtMocHelpers::MethodData<void()>(15, 4, QMC::AccessPublic, QMetaType::Void),
        // Method 'cycleSort'
        QtMocHelpers::MethodData<void()>(16, 4, QMC::AccessPublic, QMetaType::Void),
    };
    QtMocHelpers::UintData qt_properties {
        // property 'count'
        QtMocHelpers::PropertyData<int>(17, QMetaType::Int, QMC::DefaultPropertyFlags, 0),
        // property 'filter'
        QtMocHelpers::PropertyData<QString>(18, QMetaType::QString, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet, 1),
        // property 'activeRow'
        QtMocHelpers::PropertyData<int>(19, QMetaType::Int, QMC::DefaultPropertyFlags, 2),
        // property 'sortLabel'
        QtMocHelpers::PropertyData<QString>(20, QMetaType::QString, QMC::DefaultPropertyFlags, 3),
    };
    QtMocHelpers::UintData qt_enums {
    };
    QtMocHelpers::UintData qt_constructors {};
    QtMocHelpers::ClassInfos qt_classinfo({
            {    1,    2 },
    });
    return QtMocHelpers::metaObjectData<PlaylistModel, void>(QMC::MetaObjectFlag{}, qt_stringData,
            qt_methods, qt_properties, qt_enums, qt_constructors, qt_classinfo);
}
Q_CONSTINIT const QMetaObject jvp::PlaylistModel::staticMetaObject = { {
    QMetaObject::SuperData::link<QAbstractListModel::staticMetaObject>(),
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp13PlaylistModelE_t>.stringdata,
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp13PlaylistModelE_t>.data,
    qt_static_metacall,
    nullptr,
    qt_staticMetaObjectRelocatingContent<qt_meta_tag_ZN3jvp13PlaylistModelE_t>.metaTypes,
    nullptr
} };

void jvp::PlaylistModel::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    auto *_t = static_cast<PlaylistModel *>(_o);
    if (_c == QMetaObject::InvokeMetaMethod) {
        switch (_id) {
        case 0: _t->countChanged(); break;
        case 1: _t->filterChanged(); break;
        case 2: _t->activeRowChanged(); break;
        case 3: _t->sortLabelChanged(); break;
        case 4: _t->playRequested((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 5: _t->sortCycleRequested(); break;
        case 6: _t->toggleExpanded((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 7: _t->expandAll(); break;
        case 8: _t->collapseAll(); break;
        case 9: _t->playFirstMatch(); break;
        case 10: _t->cycleSort(); break;
        default: ;
        }
    }
    if (_c == QMetaObject::IndexOfMethod) {
        if (QtMocHelpers::indexOfMethod<void (PlaylistModel::*)()>(_a, &PlaylistModel::countChanged, 0))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlaylistModel::*)()>(_a, &PlaylistModel::filterChanged, 1))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlaylistModel::*)()>(_a, &PlaylistModel::activeRowChanged, 2))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlaylistModel::*)()>(_a, &PlaylistModel::sortLabelChanged, 3))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlaylistModel::*)(int )>(_a, &PlaylistModel::playRequested, 4))
            return;
        if (QtMocHelpers::indexOfMethod<void (PlaylistModel::*)()>(_a, &PlaylistModel::sortCycleRequested, 5))
            return;
    }
    if (_c == QMetaObject::ReadProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 0: *reinterpret_cast<int*>(_v) = _t->count(); break;
        case 1: *reinterpret_cast<QString*>(_v) = _t->filter(); break;
        case 2: *reinterpret_cast<int*>(_v) = _t->activeRow(); break;
        case 3: *reinterpret_cast<QString*>(_v) = _t->sortLabel(); break;
        default: break;
        }
    }
    if (_c == QMetaObject::WriteProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 1: _t->setFilter(*reinterpret_cast<QString*>(_v)); break;
        default: break;
        }
    }
}

const QMetaObject *jvp::PlaylistModel::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *jvp::PlaylistModel::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp13PlaylistModelE_t>.strings))
        return static_cast<void*>(this);
    return QAbstractListModel::qt_metacast(_clname);
}

int jvp::PlaylistModel::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QAbstractListModel::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 11)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 11;
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 11)
            *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType();
        _id -= 11;
    }
    if (_c == QMetaObject::ReadProperty || _c == QMetaObject::WriteProperty
            || _c == QMetaObject::ResetProperty || _c == QMetaObject::BindableProperty
            || _c == QMetaObject::RegisterPropertyMetaType) {
        qt_static_metacall(this, _c, _id, _a);
        _id -= 4;
    }
    return _id;
}

// SIGNAL 0
void jvp::PlaylistModel::countChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 0, nullptr);
}

// SIGNAL 1
void jvp::PlaylistModel::filterChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 1, nullptr);
}

// SIGNAL 2
void jvp::PlaylistModel::activeRowChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 2, nullptr);
}

// SIGNAL 3
void jvp::PlaylistModel::sortLabelChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 3, nullptr);
}

// SIGNAL 4
void jvp::PlaylistModel::playRequested(int _t1)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 4, nullptr, _t1);
}

// SIGNAL 5
void jvp::PlaylistModel::sortCycleRequested()
{
    QMetaObject::activate(this, &staticMetaObject, 5, nullptr);
}
QT_WARNING_POP
