#pragma once
// 재생목록 트리(폴더 계층)를 펼친 행 목록으로 QML에 보여 주는 모델.
// 폴더 접기/펼치기, 검색(파일 이름·경로 부분 일치), 재생 중·시청 완료·진행률·대기열 표시.
// YouTube로 받은 영상과 폴더 밖 파일은 가상 폴더("📺 YouTube 영상", "💾 외부 파일")로 묶습니다.

#include <QAbstractListModel>
#include <QtQml/qqmlregistration.h>
#include <QSet>
#include <QStringList>
#include <functional>
#include <memory>

namespace jvp {

class PlaylistModel : public QAbstractListModel {
    Q_OBJECT
    QML_ANONYMOUS
    Q_PROPERTY(int count READ count NOTIFY countChanged)
    Q_PROPERTY(QString filter READ filter WRITE setFilter NOTIFY filterChanged)
    Q_PROPERTY(int activeRow READ activeRow NOTIFY activeRowChanged)
    Q_PROPERTY(QString sortLabel READ sortLabel NOTIFY sortLabelChanged)
public:
    enum Role {
        DepthRole = Qt::UserRole + 1, IsFolderRole, ExpandedRole, TitleRole, PathRole, PlaylistIndexRole,
        ActiveRole, WatchedRole, ProgressRole, QueuePositionRole, MissingRole, ChildCountRole
    };
    struct Progress { double ratio = 0; bool watched = false; };

    explicit PlaylistModel(QObject *parent = nullptr);

    void setPlaylist(const QStringList &paths, const QString &root, const QString &youtubeDir);
    void setActiveIndex(int playlistIndex);
    void setQueue(const QStringList &queue);
    void setProgressProvider(std::function<Progress(const QString &)> fn) { m_progress = std::move(fn); }
    void refreshProgress();          // 이어보기·시청 완료 표시만 갱신
    void setSortLabel(const QString &label);

    int count() const { return m_paths.size(); }
    QString filter() const { return m_filter; }
    void setFilter(const QString &f);
    int activeRow() const;
    QString sortLabel() const { return m_sortLabel; }

    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    Q_INVOKABLE void toggleExpanded(int row);
    Q_INVOKABLE void expandAll();
    Q_INVOKABLE void collapseAll();
    Q_INVOKABLE void playFirstMatch();
    Q_INVOKABLE void cycleSort() { emit sortCycleRequested(); }

signals:
    void countChanged();
    void filterChanged();
    void activeRowChanged();
    void sortLabelChanged();
    void playRequested(int playlistIndex);
    void sortCycleRequested();

private:
    struct Node {
        QString name;
        QString key;                       // 폴더: 경로(펼침 상태 키), 파일: 경로
        bool folder = false;
        int playlistIndex = -1;
        int videoCount = 0;
        std::vector<std::unique_ptr<Node>> children;
        Node *child(const QString &name, const QString &key);
    };
    struct Row { const Node *node; int depth; };

    void rebuildTree();
    void rebuildRows();
    void flatten(const Node *node, int depth, QList<Row> &out) const;
    void expandToActive();

    QStringList m_paths;
    QString m_root;
    QString m_youtubeDir;
    std::unique_ptr<Node> m_tree;
    QList<Row> m_rows;
    QSet<QString> m_expanded;
    QString m_filter;
    int m_active = -1;
    QStringList m_queue;
    QString m_sortLabel = QStringLiteral("이름순");
    std::function<Progress(const QString &)> m_progress;
};

} // namespace jvp
