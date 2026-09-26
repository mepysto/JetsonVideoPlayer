#pragma once
// 파이썬 버전과 같은 위치를 씁니다 — 기존 설정·이어보기·썸네일 캐시를 그대로 이어받기 위해.
//   설정:  $XDG_CONFIG_HOME/jetson_video_player  (없으면 ~/.config/jetson_video_player)
//   캐시:  ~/.cache/jetson_video_player            (파이썬 버전도 XDG_CACHE_HOME을 따르지 않음)
//   데이터: ~/.local/share/jetson_video_player      (whisper.cpp, NLLB 모델)

#include <QDir>
#include <QString>

namespace jvp::paths {

inline QString configDir()
{
    QString base = qEnvironmentVariable("XDG_CONFIG_HOME");
    if (base.isEmpty())
        base = QDir::homePath() + QStringLiteral("/.config");
    return base + QStringLiteral("/jetson_video_player");
}

inline QString cacheDir() { return QDir::homePath() + QStringLiteral("/.cache/jetson_video_player"); }

inline QString dataDir() { return QDir::homePath() + QStringLiteral("/.local/share/jetson_video_player"); }

// 영상 폴더에 쓸 수 없을 때 AI 자막·번역·온라인 자막을 두는 곳
inline QString aiSubtitleCacheDir() { return cacheDir() + QStringLiteral("/ai_subtitles"); }

inline QString thumbRoot() { return cacheDir() + QStringLiteral("/thumbs"); }

inline QString youtubeDir() { return QDir::homePath() + QStringLiteral("/Videos/YouTube"); }

} // namespace jvp::paths
