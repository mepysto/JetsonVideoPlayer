#pragma once
// 리모컨 로그인 URL용 QR 코드 (Project Nayuki QR-Code-generator, MIT — vendor/qrcodegen.*)

#include <QImage>
#include <QString>

namespace jvp {

// 오류 정정 MEDIUM(파이썬 버전과 같음), 검은 모듈/흰 배경. 한 모듈이 scale×scale 픽셀, 둘레에 border 모듈만큼 여백
// (한 변: (모듈 수 + 2·border)·scale 픽셀). 글자가 너무 길어 만들 수 없으면 null QImage.
QImage qrImage(const QString &text, int scale = 4, int border = 2);

// 한 변의 모듈 수, 만들 수 없으면 0
int qrModuleCount(const QString &text);

} // namespace jvp
