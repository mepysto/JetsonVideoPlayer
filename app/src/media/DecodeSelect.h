#pragma once
// 디코더 자동 선택(autoplug-select) 도우미 — 분석 작업(음량·AI 자막·썸네일)이 필요한 디코더만 쓰게 합니다.
//  - 오디오만 필요할 때: 영상·이미지·자막 디코더를 고르지 않음 (NVDEC가 못 여는 영상 때문에 실패하지 않게)
//  - 소프트웨어 대체: NVDEC(nvv4l2decoder 등)를 건너뛰어 avdec_* 같은 CPU 디코더가 붙게 함
//    (PlayerEngine이 NVDEC 우선순위를 올려 두므로, 4:4:4·12비트처럼 NVDEC가 못 여는 형식은 이렇게 다시 엽니다)

#include <gst/gst.h>

namespace jvp::decodeselect {

// GstAutoplugSelectResult (공개 헤더에 없음)
constexpr gint kTry = 0, kExpose = 1, kSkip = 2;

// uridecodebin/decodebin "autoplug-select" 콜백: 영상·이미지·자막 디코더는 EXPOSE(연결하지 않고 버림)
gint skipNonAudioDecoders(GstElement *bin, GstPad *pad, GstCaps *caps, GstElementFactory *factory, gpointer);

// "autoplug-select" 콜백: Jetson 하드웨어 디코더(nvv4l2decoder, nvjpegdec …)는 SKIP
gint skipHardwareDecoders(GstElement *bin, GstPad *pad, GstCaps *caps, GstElementFactory *factory, gpointer);

// playbin 안에 생기는 decodebin마다 skipHardwareDecoders를 붙입니다 (playbin을 NULL→PAUSED로 올리기 전에 호출)
void forceSoftwareDecoding(GstElement *playbin);

} // namespace jvp::decodeselect
