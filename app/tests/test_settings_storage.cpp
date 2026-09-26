// settings.py / storage.py 이식 검증 (tests/test_storage_settings.py 대응)
#include "JsonFile.h"
#include "Settings.h"
#include "Storage.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSet>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

#include <memory>
#include <utime.h>

using namespace jvp;

namespace {
constexpr qint64 S = kNsPerSecond;

void writeFile(const QString &path, const QByteArray &bytes)
{
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly | QIODevice::Truncate));
    f.write(bytes);
}
} // namespace

class TestSettingsStorage : public QObject {
    Q_OBJECT
    QTemporaryDir m_home;
    std::unique_ptr<QTemporaryDir> m_dir;
    QString p(const QString &name) const { return m_dir->filePath(name); }

private slots:
    void initTestCase()
    {
        // 실수로 기본 경로를 쓰더라도 진짜 ~/.config, ~/.cache는 건드리지 않도록
        QVERIFY(m_home.isValid());
        qputenv("HOME", m_home.path().toUtf8());
        qputenv("XDG_CONFIG_HOME", (m_home.path() + "/config").toUtf8());
    }
    void init()
    {
        // 테스트마다 빈 폴더
        m_dir = std::make_unique<QTemporaryDir>();
        QVERIFY(m_dir->isValid());
    }

    void defaultPathsFollowHome()
    {
        QCOMPARE(Settings().path(), m_home.path() + "/config/jetson_video_player/settings.json");
        QCOMPARE(ResumeCache().path(), m_home.path() + "/.cache/jetson_video_player/resume_cache.json");
    }

    void resumeProgressAndCompletion()
    {
        const QString video = p("a.mp4");
        writeFile(video, "");
        ResumeCache rc(p("resume.json"));
        rc.set(video, 3 * S, 100 * S);   // 5초 미만은 저장하지 않음
        QCOMPARE(rc.get(video), (QPair<qint64, qint64>(0, 0)));
        rc.set(video, 40 * S, 100 * S);
        QCOMPARE(rc.get(video), (QPair<qint64, qint64>(40 * S, 100 * S)));
        auto pr = rc.progress(video);
        QVERIFY(pr.ratio.has_value());
        QVERIFY(qAbs(*pr.ratio - 0.4) < 1e-9);
        QCOMPARE(pr.watched, false);
        QCOMPARE(rc.recentInProgress(), (QList<ResumeCache::Entry>{{video, 40 * S, 100 * S}}));

        rc.set(video, 97 * S, 100 * S);   // 95% 이후 → 시청 완료
        QCOMPARE(rc.get(video), (QPair<qint64, qint64>(0, 100 * S)));
        pr = rc.progress(video);
        QVERIFY(!pr.ratio.has_value());
        QCOMPARE(pr.watched, true);
        QVERIFY(rc.recentInProgress().isEmpty());

        rc.set(video, 10 * S, 100 * S);   // 다시 보기 시작해도 완료 표시는 유지
        QCOMPARE(rc.progress(video).watched, true);

        QVERIFY(rc.isDirty());
        rc.save();
        QVERIFY(!rc.isDirty());
        ResumeCache reloaded(p("resume.json"));
        QCOMPARE(reloaded.get(video), (QPair<qint64, qint64>(10 * S, 100 * S)));
    }

    void recentInProgressSkipsMissingFiles()
    {
        ResumeCache rc(p("resume.json"));
        rc.set(p("gone.mp4"), 30 * S, 100 * S);
        QVERIFY(rc.recentInProgress().isEmpty());
        // available로 판단을 바꿀 수 있음 (끊긴 네트워크 폴더)
        QCOMPARE(rc.recentInProgress(5, [](const QString &) { return true; }).size(), 1);
    }

    void recentInProgressOrderAndLimit()
    {
        ResumeCache rc(p("resume.json"));
        for (int i = 0; i < 8; ++i) {
            rc.set(QString("/v/%1.mkv").arg(i), (10 + i) * S, 100 * S);
            QTest::qWait(2);   // updated_at이 달라지도록
        }
        const auto all = [](const QString &) { return true; };
        const auto items = rc.recentInProgress(3, all);
        QCOMPARE(items.size(), 3);
        QCOMPARE(items.at(0).path, QString("/v/7.mkv"));
        QCOMPARE(items.at(2).path, QString("/v/5.mkv"));
        rc.clear("/v/7.mkv");
        QCOMPARE(rc.recentInProgress(1, all).at(0).path, QString("/v/6.mkv"));
    }

    void resumePrunesOldestOnSave()
    {
        // 파이썬 형식 파일을 직접 만들어 MAX_ENTRIES 정리 확인
        QJsonObject data;
        for (int i = 0; i < ResumeCache::kMaxEntries + 5; ++i)
            data.insert(QString("/v/%1.mkv").arg(i, 4, 10, QChar('0')),
                        QJsonObject{{"position_ns", 10 * S}, {"duration_ns", 100 * S}, {"updated_at", 1000.0 + i},
                                    {"watched", false}});
        data.insert("/junk", 5);   // 객체가 아닌 항목은 버림
        QVERIFY(json::writeAtomic(p("resume.json"), data));
        ResumeCache rc(p("resume.json"));
        QCOMPARE(rc.get("/junk"), (QPair<qint64, qint64>(0, 0)));
        rc.set("/v/new.mkv", 20 * S, 100 * S);
        rc.save();
        const QJsonObject saved = json::readObject(p("resume.json"));
        QCOMPARE(saved.size(), ResumeCache::kMaxEntries);
        QVERIFY(saved.contains("/v/new.mkv"));
        QVERIFY(!saved.contains("/v/0000.mkv"));
        QVERIFY(!saved.contains("/v/0005.mkv"));
        QVERIFY(saved.contains("/v/0006.mkv"));
    }

    void settingsRoundtripAndValidation()
    {
        const QString path = p("settings.json");
        Settings st(path);
        QCOMPARE(st.value("volume"), Settings::defaultValue("volume"));
        QCOMPARE(st.save(), false);   // 변경 없으면 쓰지 않음
        QVERIFY(!QFile::exists(path));
        st.update({{"volume", 250}, {"repeat_mode", "one"}, {"subtitle_font_scale", 1.2}});
        QCOMPARE(st.value("volume").toInt(), 200);   // 범위 제한
        QCOMPARE(st.save(), true);
        QCOMPARE(st.save(), false);
        Settings again(path);
        QCOMPARE(again.value("repeat_mode").toString(), QString("one"));
        QCOMPARE(again.value("subtitle_font_scale").toDouble(), 1.2);
        QCOMPARE(again.value("volume").metaType().id(), int(QMetaType::Int));
    }

    void settingsValidationRules()
    {
        Settings st(p("settings.json"));
        QCOMPARE(st.setValue("volume", -5).toInt(), 0);
        QCOMPARE(st.setValue("volume", 55.9).toInt(), 55);          // int()처럼 버림
        QCOMPARE(st.setValue("volume", true), QVariant(100));        // bool은 숫자가 아님
        QCOMPARE(st.setValue("subtitle_font_scale", 3).toDouble(), 1.6);
        QCOMPARE(st.value("subtitle_font_scale").metaType().id(), int(QMetaType::Double));
        QCOMPARE(st.setValue("mini_x", -100).toInt(), -1);
        QCOMPARE(st.setValue("muted", 1).toBool(), false);           // bool 자리에 숫자는 거부
        QCOMPARE(st.setValue("muted", true).toBool(), true);
        QCOMPARE(st.setValue("eq_preset", "bass").toString(), QString("bass"));
        QCOMPARE(st.setValue("eq_preset", "loud").toString(), QString("flat"));
        QCOMPARE(st.setValue("translate_backend", "claude").toString(), QString("claude"));
        QCOMPARE(st.setValue("remote_pin", 1234).toString(), QString(""));
        QCOMPARE(st.setValue("whisper_model", "base").toString(), QString("base"));   // 선택지 없는 문자열은 그대로
        QCOMPARE(st.value("ui_mode").toString(), QString("auto"));
        QCOMPARE(st.setValue("ui_mode", "tv").toString(), QString("tv"));
        QCOMPARE(st.setValue("ui_mode", "phone").toString(), QString("auto"));
        QVERIFY(Settings::keys().contains("autoplay_countdown"));
        QVERIFY(Settings::keys().contains("sidebar_visible"));
    }

    void settingsSignalsAndUnknownKeys()
    {
        Settings st(p("settings.json"));
        QSignalSpy spy(&st, &Settings::valueChanged);
        st.setValue("night_mode", true);
        st.setValue("night_mode", true);   // 같은 값이면 신호 없음
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.at(0).at(0).toString(), QString("night_mode"));
        QTest::ignoreMessage(QtWarningMsg, QRegularExpression("알 수 없는 설정 키"));
        QVERIFY(!st.setValue("bogus_key", 5).isValid());
        QCOMPARE(spy.count(), 1);
    }

    void settingsIgnoresCorruptValues()
    {
        const QString path = p("settings.json");
        writeFile(path, R"({"volume": "loud", "repeat_mode": "bogus", "muted": 1, "unknown": 5, "window_width": 800.7})");
        Settings st(path);
        QCOMPARE(st.value("volume"), Settings::defaultValue("volume"));
        QCOMPARE(st.value("repeat_mode"), Settings::defaultValue("repeat_mode"));
        QCOMPARE(st.value("muted"), QVariant(false));
        QCOMPARE(st.value("window_width"), QVariant(800));
        // 정규화된 값이 저장본과 같다고 보므로 불러오기만으로는 쓰지 않음
        QCOMPARE(st.save(), false);
    }

    void settingsSurvivesGarbageFile()
    {
        writeFile(p("settings.json"), "{not json");
        QCOMPARE(Settings(p("settings.json")).value("volume"), QVariant(100));
        writeFile(p("list.json"), "[1, 2]");
        QCOMPARE(Settings(p("list.json")).value("volume"), QVariant(100));
    }

    void settingsKeepListValues()
    {
        Settings s(p("settings.json"));
        const QVariantMap loc{{"uri", "smb://nas/v"}, {"path", "/p"}, {"name", "n"}};
        s.setValue("network_locations", QVariantList{loc});
        QVariantList got = s.value("network_locations").toList();
        got.append("mutated");
        QCOMPARE(s.value("network_locations").toList(), QVariantList{loc});
        s.setValue("network_locations", "not a list");
        QCOMPARE(s.value("network_locations").toList(), QVariantList());
        s.setValue("network_locations", QVariantList{loc});
        QVERIFY(s.save());
        QCOMPARE(Settings(p("settings.json")).value("network_locations").toList(), QVariantList{loc});
    }

    void bookmarks()
    {
        const QString path = p("bm.json");
        BookmarkCache bc(path);
        QCOMPARE(bc.add("/v.mp4", 65 * S), (QPair<bool, QString>(true, "01:05")));
        QCOMPARE(bc.add("/v.mp4", qint64(65.5 * S)).first, false);   // 1초 이내 중복
        QCOMPARE(bc.add("/v.mp4", 3725 * S), (QPair<bool, QString>(true, "01:02:05")));
        QCOMPARE(bc.add("/v.mp4", 10 * S, "intro"), (QPair<bool, QString>(true, "intro")));
        auto labels = [](const QVariantList &l) {
            QStringList out;
            for (const QVariant &v : l)
                out << v.toMap().value("label").toString();
            return out;
        };
        QCOMPARE(labels(bc.get("/v.mp4")), (QStringList{"intro", "01:05", "01:02:05"}));   // 시간순
        QVERIFY(bc.remove("/v.mp4", 0));
        QVERIFY(!bc.remove("/v.mp4", 9));
        QCOMPARE(bc.add("", 0).first, false);
        bc.save();
        BookmarkCache reloaded(path);
        QCOMPARE(labels(reloaded.get("/v.mp4")), (QStringList{"01:05", "01:02:05"}));
        QCOMPARE(reloaded.get("/v.mp4").at(0).toMap().value("position_ns").toLongLong(), 65 * S);
    }

    void historyOrderDedupeLimit()
    {
        HistoryCache hc(p("h.json"));
        QStringList files;
        for (int i = 0; i < kHistoryLimit + 3; ++i) {
            const QString f = p(QString("v%1.mp4").arg(i));
            writeFile(f, "");
            files << f;
            hc.add(f);
        }
        hc.add(files[5]);   // 다시 보면 맨 앞으로
        const QVariantList items = hc.all();
        QCOMPARE(items.size(), kHistoryLimit);
        QCOMPARE(items.at(0).toMap().value("path").toString(), files[5]);
        QSet<QString> unique;
        for (const QVariant &v : items)
            unique.insert(v.toMap().value("path").toString());
        QCOMPARE(unique.size(), kHistoryLimit);
        hc.add(p("missing.mp4"));   // 없는 파일은 무시
        QCOMPARE(hc.all().at(0).toMap().value("path").toString(), files[5]);
        const QVariantMap first = hc.all().at(0).toMap();
        QCOMPARE(first.value("title").toString(), QString("v5.mp4"));
        QCOMPARE(first.value("is_dir").toBool(), false);
        hc.add(m_dir->path());
        QCOMPARE(hc.all().at(0).toMap().value("is_dir").toBool(), true);
        hc.save();
        QCOMPARE(json::readArray(p("h.json")).size(), kHistoryLimit);
    }

    void hwCacheInvalidatesOnChangeAndVersion()
    {
        const QString video = p("a.mp4");
        writeFile(video, "x");
        const QString path = p("hw.json");
        HWSupportCache hc(path);
        hc.set(video, true, "ok");
        QCOMPARE(hc.get(video), (std::optional<QPair<bool, QString>>(QPair<bool, QString>(true, "ok"))));
        writeFile(video, "xx");   // 파일이 바뀌면 다시 검사
        QVERIFY(!hc.get(video).has_value());
        hc.set(video, false, "no");
        hc.save();
        // 저장 후 다시 읽어도 mtime 실수가 정확히 같아야 함
        QCOMPARE(HWSupportCache(path).get(video)->second, QString("no"));
        QJsonObject data = json::readObject(path);
        QJsonObject e = data.value(video).toObject();
        e.insert("v", 1);   // 이전 버전 판정은 무시
        data.insert(video, e);
        QVERIFY(json::writeAtomic(path, data));
        QVERIFY(!HWSupportCache(path).get(video).has_value());
    }

    void hwCacheReadsPythonMtime()
    {
        // 파이썬이 쓴 st_mtime(나노초 포함 실수)과 정확히 일치하는지 — 파일 시각을 알려진 값으로 고정
        const QString video = p("b.mp4");
        writeFile(video, "abc");
        struct utimbuf t {1700000000, 1700000000};
        QCOMPARE(::utime(QFile::encodeName(video).constData(), &t), 0);
        writeFile(p("hw.json"), QString(R"({"%1": {"mtime": 1700000000.0, "size": 3, "supported": true, "reason": "H264", "v": 2}})")
                                    .arg(video).toUtf8());
        QCOMPARE(HWSupportCache(p("hw.json")).get(video)->second, QString("H264"));
    }

    void storesSurviveWrongJsonTypes()
    {
        writeFile(p("bm.json"), "[1, 2]");
        writeFile(p("h.json"), R"({"a": 1})");
        QVERIFY(BookmarkCache(p("bm.json")).get("/x").isEmpty());
        QVERIFY(HistoryCache(p("h.json")).all().isEmpty());
        writeFile(p("r.json"), "garbage");
        QCOMPARE(ResumeCache(p("r.json")).get("/x"), (QPair<qint64, qint64>(0, 0)));
    }

    void loudnessCache()
    {
        const QString video = p("a.mkv");
        writeFile(video, "abc");
        const QString key = fileKey(video);
        QVERIFY(key.startsWith(video + "|3|"));
        QVERIFY(fileKey(p("gone.mkv")).isNull());

        LoudnessCache lc(p("loud.json"));
        QCOMPARE(lc.lookup(video).first, false);
        lc.store(video, -23.456);
        auto r = lc.lookup(video);
        QVERIFY(r.first && r.second.has_value());
        QCOMPARE(*r.second, -23.46);
        const QString silent = p("b.mkv");
        writeFile(silent, "x");
        lc.store(silent, std::nullopt);   // 오디오 없음도 "측정함"으로 기억
        QVERIFY(lc.lookup(silent).first && !lc.lookup(silent).second.has_value());
        lc.store(p("gone.mkv"), -10);     // 없는 파일은 무시
        lc.save();

        LoudnessCache reloaded(p("loud.json"));
        QCOMPARE(*reloaded.lookup(video).second, -23.46);
        QVERIFY(reloaded.lookup(silent).first);
        // 형식이 틀린 값은 버림
        writeFile(p("bad.json"), QString(R"({"%1": "loud"})").arg(key).toUtf8());
        QCOMPARE(LoudnessCache(p("bad.json")).lookup(video).first, false);
    }

    void loudnessKeepsNewestEntries()
    {
        LoudnessCache lc(p("loud.json"));
        QStringList files;
        for (int i = 0; i < LoudnessCache::kMaxEntries + 3; ++i) {
            const QString f = p(QString("f%1.mkv").arg(i));
            writeFile(f, "x");
            files << f;
        }
        lc.store(files[0], -1);
        for (int i = 1; i < files.size(); ++i)
            lc.store(files[i], -20);
        lc.store(files[0], -5);   // 다시 저장하면 최신으로
        lc.save();
        LoudnessCache reloaded(p("loud.json"));
        QVERIFY(reloaded.lookup(files[0]).first);
        QVERIFY(!reloaded.lookup(files[1]).first);
        QVERIFY(!reloaded.lookup(files[3]).first);
        QVERIFY(reloaded.lookup(files[4]).first);
        QVERIFY(reloaded.lookup(files.last()).first);
        // 저장 파일이 순서를 지키는 유효한 JSON인지
        QCOMPARE(json::readObject(p("loud.json")).size(), LoudnessCache::kMaxEntries);
    }

    void atomicWriteCreatesParents()
    {
        const QString path = p("deep/er/x.json");
        QVERIFY(json::writeAtomic(path, QJsonObject{{"한글", "값"}}));
        bool ok = false;
        QCOMPARE(json::readObject(path, &ok).value("한글").toString(), QString("값"));
        QVERIFY(ok);
        json::read(p("nope.json"), &ok);
        QVERIFY(!ok);
        QCOMPARE(json::serializeOrderedObject({}), QByteArray("{}\n"));
        const QByteArray ordered = json::serializeOrderedObject({{"b", 1}, {"a", QJsonValue()}});
        QVERIFY(ordered.indexOf("\"b\"") < ordered.indexOf("\"a\""));
        QJsonParseError err;
        QJsonDocument::fromJson(ordered, &err);
        QCOMPARE(err.error, QJsonParseError::NoError);
    }
};

QTEST_GUILESS_MAIN(TestSettingsStorage)
#include "test_settings_storage.moc"
