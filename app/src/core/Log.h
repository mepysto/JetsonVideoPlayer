#pragma once
// 로그 설정 (파이썬 log.py 이식): 터미널(메시지만, 기존과 같은 이모지 메시지) + 회전 로그 파일.
// main()이 시작할 때 setupLogging()을 부릅니다. JVP_LOG_LEVEL=DEBUG 로 jvp.* 디버그 로그를 볼 수 있습니다.

#include <QString>

namespace jvp::log {

constexpr qint64 kMaxBytes = 1024 * 1024;   // 1 MB마다 회전
constexpr int kBackups = 3;                 // player.log.1 ~ .3

QString defaultLogFile();                   // paths::cacheDir()/player.log

// Qt 메시지 처리기를 설치합니다. level이 비면 JVP_LOG_LEVEL(DEBUG/INFO/WARNING/ERROR, 기본 INFO).
// 알 수 없는 이름은 INFO. logFile이 비면 터미널만 씁니다 (파일을 열 수 없을 때도).
// 반환: 실제 적용된 수준 이름
QString setupLogging(const QString &level = QString(), const QString &logFile = defaultLogFile());
// 처리기를 원래대로 되돌리고 파일을 닫습니다 (테스트용)
void shutdownLogging();

QString logFilePath();                      // 지금 쓰는 로그 파일 (없으면 빈 문자열)
QString currentLevel();                     // "DEBUG" / "INFO" / "WARNING" / "ERROR"

} // namespace jvp::log
