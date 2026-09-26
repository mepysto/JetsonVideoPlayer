/****************************************************************************
** Generated QML type registration code
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include <QtQml/qqml.h>
#include <QtQml/qqmlmoduleregistration.h>

#if __has_include(<AiController.h>)
#  include <AiController.h>
#endif
#if __has_include(<AppController.h>)
#  include <AppController.h>
#endif
#if __has_include(<OnlineSubsController.h>)
#  include <OnlineSubsController.h>
#endif
#if __has_include(<PlaylistModel.h>)
#  include <PlaylistModel.h>
#endif
#if __has_include(<RemoteInfo.h>)
#  include <RemoteInfo.h>
#endif
#if __has_include(<SubtitleController.h>)
#  include <SubtitleController.h>
#endif
#if __has_include(<SubtitleOverlay.h>)
#  include <SubtitleOverlay.h>
#endif
#if __has_include(<VideoItem.h>)
#  include <VideoItem.h>
#endif


#if !defined(QT_STATIC)
#define Q_QMLTYPE_EXPORT Q_DECL_EXPORT
#else
#define Q_QMLTYPE_EXPORT
#endif
Q_QMLTYPE_EXPORT void qml_register_types_JetsonPlayer()
{
    QT_WARNING_PUSH QT_WARNING_DISABLE_DEPRECATED
    QMetaType::fromType<QAbstractItemModel *>().id();
    qmlRegisterEnum<QAbstractItemModel::LayoutChangeHint>("QAbstractItemModel::LayoutChangeHint");
    qmlRegisterEnum<QAbstractItemModel::CheckIndexOption>("QAbstractItemModel::CheckIndexOption");
    QMetaType::fromType<QAbstractListModel *>().id();
    qmlRegisterTypesAndRevisions<jvp::AiController>("JetsonPlayer", 1);
    qmlRegisterTypesAndRevisions<jvp::AppController>("JetsonPlayer", 1);
    qmlRegisterTypesAndRevisions<jvp::OnlineSubsController>("JetsonPlayer", 1);
    qmlRegisterTypesAndRevisions<jvp::PlaylistModel>("JetsonPlayer", 1);
    qmlRegisterTypesAndRevisions<jvp::RemoteInfo>("JetsonPlayer", 1);
    qmlRegisterTypesAndRevisions<jvp::SubtitleController>("JetsonPlayer", 1);
    qmlRegisterTypesAndRevisions<jvp::SubtitleOverlay>("JetsonPlayer", 1);
    qmlRegisterAnonymousType<QQuickItem, 254>("JetsonPlayer", 1);
    qmlRegisterTypesAndRevisions<jvp::TranslationController>("JetsonPlayer", 1);
    qmlRegisterTypesAndRevisions<jvp::VideoItem>("JetsonPlayer", 1);
    QT_WARNING_POP
    qmlRegisterModule("JetsonPlayer", 1, 0);
}

static const QQmlModuleRegistration jetsonPlayerRegistration("JetsonPlayer", qml_register_types_JetsonPlayer);
