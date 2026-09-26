#include "PlaylistModel.h"

#include <QDir>
#include <QFileInfo>

namespace jvp {

namespace {
constexpr int kExpandAllLimit = 300;   // 이보다 작으면 처음에 모든 폴더를 펼침
const QString kYoutubeKey = QStringLiteral("::youtube");
const QString kExternalKey = QStringLiteral("::external");

bool isSubPath(const QString &child, const QString &parent)
{
    if (parent.isEmpty())
        return false;
    const QString rel = QDir(parent).relativeFilePath(child);
    return !rel.startsWith(QLatin1String("..")) && !QDir::isAbsolutePath(rel);
}
} // namespace

PlaylistModel::Node *PlaylistModel::Node::child(const QString &n, const QString &k)
{
    for (auto &c : children)
        if (c->folder && c->key == k)
            return c.get();
    auto node = std::make_unique<Node>();
    node->name = n;
    node->key = k;
    node->folder = true;
    children.push_back(std::move(node));
    return children.back().get();
}

PlaylistModel::PlaylistModel(QObject *parent) : QAbstractListModel(parent) {}

void PlaylistModel::setPlaylist(const QStringList &paths, const QString &root, const QString &youtubeDir)
{
    const bool firstLoad = m_paths.isEmpty() || root != m_root;
    m_paths = paths;
    m_root = QFileInfo(root).isDir() ? QFileInfo(root).absoluteFilePath() : QString();
    m_youtubeDir = youtubeDir;
    rebuildTree();
    if (firstLoad) {
        m_expanded.clear();
        if (m_paths.size() < kExpandAllLimit)
            expandAll();
    }
    expandToActive();
    rebuildRows();
    emit countChanged();
}

void PlaylistModel::rebuildTree()
{
    m_tree = std::make_unique<Node>();
    m_tree->folder = true;
    const QString needle = m_filter.toLower();
    for (int i = 0; i < m_paths.size(); ++i) {
        const QString &p = m_paths[i];
        const QString name = QFileInfo(p).fileName();
        if (!needle.isEmpty() && !name.toLower().contains(needle) && !p.toLower().contains(needle))
            continue;
        Node *parent = m_tree.get();
        if (!m_root.isEmpty()) {
            if (isSubPath(p, m_root)) {
                const QStringList parts = QDir(m_root).relativeFilePath(QFileInfo(p).absolutePath()).split('/', Qt::SkipEmptyParts);
                QString key = m_root;
                for (const QString &part : parts) {
                    if (part == QLatin1String("."))
                        continue;
                    key += '/' + part;
                    parent = parent->child(part, key);
                }
            } else if (!m_youtubeDir.isEmpty() && isSubPath(p, m_youtubeDir)) {
                parent = parent->child(QStringLiteral("📺 YouTube 영상"), kYoutubeKey);
            } else {
                parent = parent->child(QStringLiteral("💾 외부 파일"), kExternalKey);
            }
        }
        auto leaf = std::make_unique<Node>();
        leaf->name = name;
        leaf->key = p;
        leaf->playlistIndex = i;
        parent->children.push_back(std::move(leaf));
    }
    // 폴더마다 영상 수 (재귀)
    std::function<int(Node *)> count = [&](Node *n) {
        if (!n->folder)
            return 1;
        int c = 0;
        for (auto &ch : n->children)
            c += count(ch.get());
        n->videoCount = c;
        return c;
    };
    count(m_tree.get());
}

void PlaylistModel::flatten(const Node *node, int depth, QList<Row> &out) const
{
    // 폴더 먼저, 그 안에서는 재생목록 순서
    for (const auto &c : node->children)
        if (c->folder) {
            out << Row{c.get(), depth};
            if (!m_filter.isEmpty() || m_expanded.contains(c->key))
                flatten(c.get(), depth + 1, out);
        }
    for (const auto &c : node->children)
        if (!c->folder)
            out << Row{c.get(), depth};
}

void PlaylistModel::rebuildRows()
{
    const int oldActive = activeRow();
    beginResetModel();
    m_rows.clear();
    if (m_tree)
        flatten(m_tree.get(), 0, m_rows);
    endResetModel();
    if (activeRow() != oldActive)
        emit activeRowChanged();
}

void PlaylistModel::expandToActive()
{
    if (m_active < 0 || m_active >= m_paths.size() || m_root.isEmpty())
        return;
    const QString p = m_paths[m_active];
    if (isSubPath(p, m_root)) {
        QString key = m_root;
        const QStringList parts = QDir(m_root).relativeFilePath(QFileInfo(p).absolutePath()).split('/', Qt::SkipEmptyParts);
        for (const QString &part : parts) {
            if (part == QLatin1String("."))
                continue;
            key += '/' + part;
            m_expanded.insert(key);
        }
    } else if (!m_youtubeDir.isEmpty() && isSubPath(p, m_youtubeDir)) {
        m_expanded.insert(kYoutubeKey);
    } else {
        m_expanded.insert(kExternalKey);
    }
}

void PlaylistModel::setActiveIndex(int playlistIndex)
{
    if (playlistIndex == m_active)
        return;
    m_active = playlistIndex;
    expandToActive();
    rebuildRows();
    emit activeRowChanged();
}

void PlaylistModel::setQueue(const QStringList &queue)
{
    m_queue = queue;
    if (!m_rows.isEmpty())
        emit dataChanged(index(0), index(m_rows.size() - 1), {QueuePositionRole});
}

void PlaylistModel::refreshProgress()
{
    if (!m_rows.isEmpty())
        emit dataChanged(index(0), index(m_rows.size() - 1), {WatchedRole, ProgressRole, MissingRole});
}

void PlaylistModel::setSortLabel(const QString &label)
{
    if (label == m_sortLabel)
        return;
    m_sortLabel = label;
    emit sortLabelChanged();
}

void PlaylistModel::setFilter(const QString &f)
{
    const QString t = f.trimmed();
    if (t == m_filter)
        return;
    m_filter = t;
    rebuildTree();
    rebuildRows();
    emit filterChanged();
}

int PlaylistModel::activeRow() const
{
    for (int i = 0; i < m_rows.size(); ++i)
        if (!m_rows[i].node->folder && m_rows[i].node->playlistIndex == m_active)
            return i;
    return -1;
}

int PlaylistModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : m_rows.size();
}

QVariant PlaylistModel::data(const QModelIndex &idx, int role) const
{
    if (!idx.isValid() || idx.row() >= m_rows.size())
        return {};
    const Row &r = m_rows[idx.row()];
    const Node *n = r.node;
    switch (role) {
    case DepthRole: return r.depth;
    case IsFolderRole: return n->folder;
    case ExpandedRole: return n->folder && (!m_filter.isEmpty() || m_expanded.contains(n->key));
    case TitleRole: return n->name;
    case PathRole: return n->folder ? QString() : n->key;
    case PlaylistIndexRole: return n->playlistIndex;
    case ActiveRole: return !n->folder && n->playlistIndex == m_active;
    case ChildCountRole: return n->videoCount;
    case QueuePositionRole: return n->folder ? 0 : int(m_queue.indexOf(n->key)) + 1;
    case MissingRole:
        return !n->folder && !n->key.startsWith(QLatin1String("http")) && !QFileInfo::exists(n->key);
    case WatchedRole:
    case ProgressRole: {
        if (n->folder || !m_progress)
            return role == WatchedRole ? QVariant(false) : QVariant(0.0);
        const Progress pr = m_progress(n->key);
        return role == WatchedRole ? QVariant(pr.watched) : QVariant(pr.ratio);
    }
    default: return {};
    }
}

QHash<int, QByteArray> PlaylistModel::roleNames() const
{
    return {{DepthRole, "depth"}, {IsFolderRole, "isFolder"}, {ExpandedRole, "expanded"}, {TitleRole, "title"},
            {PathRole, "path"}, {PlaylistIndexRole, "playlistIndex"}, {ActiveRole, "active"}, {WatchedRole, "watched"},
            {ProgressRole, "progress"}, {QueuePositionRole, "queuePosition"}, {MissingRole, "missing"},
            {ChildCountRole, "childCount"}};
}

void PlaylistModel::toggleExpanded(int row)
{
    if (row < 0 || row >= m_rows.size() || !m_rows[row].node->folder || !m_filter.isEmpty())
        return;
    const QString key = m_rows[row].node->key;
    if (m_expanded.contains(key))
        m_expanded.remove(key);
    else
        m_expanded.insert(key);
    rebuildRows();
}

void PlaylistModel::expandAll()
{
    std::function<void(const Node *)> walk = [&](const Node *n) {
        for (const auto &c : n->children)
            if (c->folder) {
                m_expanded.insert(c->key);
                walk(c.get());
            }
    };
    if (m_tree)
        walk(m_tree.get());
    rebuildRows();
}

void PlaylistModel::collapseAll()
{
    // 전체를 접되 재생 중인 영상의 폴더는 열어 둡니다
    m_expanded.clear();
    expandToActive();
    rebuildRows();
}

void PlaylistModel::playFirstMatch()
{
    for (const Row &r : std::as_const(m_rows))
        if (!r.node->folder) {
            emit playRequested(r.node->playlistIndex);
            return;
        }
}

} // namespace jvp
