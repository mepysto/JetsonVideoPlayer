#pragma once
// 네트워크 폴더(SMB/NFS 등) 주소 다루기 — 파이썬 network.py의 순수 함수 부분 이식.
// 마운트한 공유는 gvfs-fuse 경로(/run/user/<uid>/gvfs/…) 아래 일반 파일처럼 보입니다. 주소와 로컬 경로의 대응은
// settings["network_locations"]에 [{uri, path, name}]로 저장해 두고, 재부팅 뒤 이어보기 때 다시 마운트합니다.
// (실제 마운트는 GIO를 쓰는 서비스 쪽 몫)

#include <QString>
#include <QStringList>
#include <QVariantList>

namespace jvp::network {

const QStringList &networkSchemes();   // smb nfs sftp ftp ftps dav davs afp
constexpr int kMaxLocations = 10;

QString gvfsRoot();                     // $XDG_RUNTIME_DIR/gvfs (없으면 /run/user/<uid>/gvfs)
bool isGvfsPath(const QString &path);
bool isNetworkUri(const QString &text);
// \\서버\공유 (Windows 표기) → smb://서버/공유, 스킴 소문자, 끝의 / 제거
QString normalizeUri(const QString &text);
// 목록에 보일 짧은 이름: 서버/공유/폴더 (퍼센트 인코딩 풀어서)
QString displayName(const QString &uri);

// 설정 값 검증: QVariantMap{uri, path, name} 목록, 같은 주소는 한 번만, 최대 kMaxLocations개
QVariantList cleanLocations(const QVariant &value);
// 최근 사용한 위치를 맨 앞으로
QVariantList rememberLocation(const QVariantList &locations, const QString &uri, const QString &path);
// 로컬 gvfs 경로를 저장된 위치의 네트워크 주소로 되돌립니다 (재마운트용). 모르면 null QString
QString uriForPath(const QVariantList &locations, const QString &path);

} // namespace jvp::network
