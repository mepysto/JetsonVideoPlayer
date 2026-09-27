#include "VideoItem.h"

#include "FrameBridge.h"

#include <QOpenGLContext>
#include <QOpenGLExtraFunctions>
#include <QQuickWindow>
#include <QSGSimpleTextureNode>
#include <QSGTexture>
#include <QtQuick/qsgtexture_platform.h>
#include <QLoggingCategory>
#include <QElapsedTimer>
#include <QHash>
#include <QScreen>
#include <array>

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>
#include <gst/video/video.h>

#ifdef JVP_HAVE_NVMM
#include <nvbufsurface.h>
#endif

#ifndef DRM_FORMAT_ABGR8888
#define DRM_FORMAT_ABGR8888 0x34324241   // 'AB24' = 메모리 순서 R,G,B,A
#endif

Q_LOGGING_CATEGORY(lcVideo, "jvp.video")

namespace jvp {

namespace {

const char *kVertex = R"(
attribute vec2 a_pos;
attribute vec2 a_tex;
uniform mat4 u_mvp;
varying vec2 v_tex;
void main() {
  gl_Position = u_mvp * vec4(a_pos, 0.0, 1.0);
  v_tex = a_tex;
}
)";

// HDR(PQ/HLG) → SDR 톤매핑: 파이썬 버전 jetson_player/media/hdr.py 와 같은 계산.
// u_hdr: 0 SDR, 1 PQ, 2 HLG / u_fixm: 1이면 BT.709 행렬로 만들어진 RGB를 BT.2020 기준으로 다시 계산 (HW 경로)
const char *kToneMap = R"(
uniform float u_hdr;
uniform float u_fixm;
const vec3 LUMA = vec3(0.2627, 0.6780, 0.0593);
vec3 tonemap(vec3 e) {
  if (u_hdr < 0.5) return e;
  if (u_fixm > 0.5) {
    // RGB(709 행렬) → Y'CbCr → RGB(2020 행렬)
    float y = dot(e, vec3(0.2126, 0.7152, 0.0722));
    float cb = (e.b - y) / 1.8556;
    float cr = (e.r - y) / 1.5748;
    e = vec3(y + 1.4746 * cr, y - 0.16455312684366 * cb - 0.57135312684366 * cr, y + 1.8814 * cb);
  }
  e = clamp(e, 0.0, 1.0);
  vec3 nits;
  if (u_hdr < 1.5) {
    vec3 p = pow(e, vec3(1.0 / 78.84375));
    nits = 10000.0 * pow(max(p - 0.8359375, 0.0) / (18.8515625 - 18.6875 * p), vec3(1.0 / 0.1593017578125));
  } else {
    vec3 lo = e * e / 3.0;
    vec3 hi = (exp((e - 0.55991073) / 0.17883277) + 0.28466892) / 12.0;
    vec3 scene = mix(lo, hi, step(0.5, e));
    float ys = max(dot(scene, LUMA), 1e-6);
    nits = 1000.0 * pow(ys, 0.2) * scene;
  }
  vec3 lin = nits / 203.0;
  float yl = dot(lin, LUMA);
  float t = yl <= 0.75 ? yl : 0.75 + 0.25 * (1.0 - exp(-(yl - 0.75) / 0.25));
  lin = yl > 0.0 ? lin * (t / yl) : lin;
  mat3 to709 = mat3(1.6605, -0.1246, -0.0182, -0.5876, 1.1329, -0.1006, -0.0728, -0.0083, 1.1187);
  vec3 o = clamp(to709 * lin, 0.0, 1.0);
  return pow(o, vec3(1.0 / 2.2));
}
)";

const char *kFragExternal = R"(
#extension GL_OES_EGL_image_external : require
precision highp float;
varying vec2 v_tex;
uniform samplerExternalOES u_tex0;
)";
const char *kFragExternalMain = R"(
void main() {
  gl_FragColor = vec4(tonemap(texture2D(u_tex0, v_tex).rgb), 1.0);
}
)";

const char *kFragPlanar = R"(
precision highp float;
varying vec2 v_tex;
uniform sampler2D u_tex0;
uniform sampler2D u_tex1;
uniform sampler2D u_tex2;
uniform float u_fmt;          // 0 RGBA, 1 I420, 2 NV12
uniform mat3 u_yuv;           // Y'CbCr → R'G'B'
uniform vec3 u_offset;        // 범위 보정 (제한 범위면 16/255 등)
uniform vec3 u_scale;
)";
const char *kFragPlanarMain = R"(
void main() {
  vec3 rgb;
  if (u_fmt < 0.5) {
    rgb = texture2D(u_tex0, v_tex).rgb;
  } else {
    vec3 yuv;
    yuv.x = texture2D(u_tex0, v_tex).r;
    if (u_fmt < 1.5) {
      yuv.y = texture2D(u_tex1, v_tex).r;
      yuv.z = texture2D(u_tex2, v_tex).r;
    } else {
      yuv.yz = texture2D(u_tex1, v_tex).ra;
    }
    yuv = (yuv - u_offset) * u_scale;
    rgb = u_yuv * yuv;
  }
  gl_FragColor = vec4(tonemap(clamp(rgb, 0.0, 1.0)), 1.0);
}
)";

struct YuvMatrix {
    float m[9];
};

// 열 우선 mat3: R = y + 2(1-kr)cr, G = y - ..., B = y + 2(1-kb)cb
YuvMatrix matrixFor(double kr, double kb)
{
    const double kg = 1 - kr - kb;
    const double rcr = 2 * (1 - kr), bcb = 2 * (1 - kb);
    const double gcb = -bcb * kb / kg, gcr = -rcr * kr / kg;
    return {{1.f, 1.f, 1.f, 0.f, float(gcb), float(bcb), float(rcr), float(gcr), 0.f}};
}

// 렌더 스레드에서 영상 프레임을 자체 FBO 텍스처에 그립니다 (셰이더: YUV/외부 텍스처, HDR 톤매핑, 회전).
// Qt 6.4(RHI)의 QSGRenderNode는 행렬이 유효하지 않아, beforeRendering에서 직접 그린 텍스처를
// QSGSimpleTextureNode로 넘기는 방식을 씁니다 (창 크기 GPU 패스 1번, CPU 복사 없음).
class VideoRenderer : public QObject {
public:
    explicit VideoRenderer(QQuickWindow *window) : m_window(window) {}
    ~VideoRenderer() override { releaseResources(); }

    struct Params {
        QPointer<FrameBridge> bridge;
        QSize targetSize;      // 그릴 픽셀 크기 (영상 영역 × 장치 픽셀 비율)
        QString rotation;
        int hdr = 0;
        bool fixm = false;
        qint64 vsyncNs = 16666667;   // 화면 갱신 주기
    };
    void setParams(const Params &p)
    {
        if (p.rotation != m_params.rotation || p.hdr != m_params.hdr || p.fixm != m_params.fixm)
            m_dirty = true;
        m_params = p;
    }
    // 동기화 단계(렌더 스레드, GL 컨텍스트 활성)에서 그릴 대상 텍스처를 미리 준비합니다.
    void prepareTarget()
    {
        if (QOpenGLContext *ctx = QOpenGLContext::currentContext(); ctx && !m_params.targetSize.isEmpty())
            ensureFbo(ctx->extraFunctions(), m_params.targetSize);
    }
    GLuint texture() const { return m_fboTex; }
    QSize textureSize() const { return m_fboSize; }
    bool hasFrame() const { return m_ready; }
    void render();
    void paceBeforeSwap();
    void markSwapped() { m_lastSwapNs = g_get_monotonic_time() * 1000; }
    void releaseResources();

private:
    bool ensurePrograms(QOpenGLExtraFunctions *f);
    void ensureFbo(QOpenGLExtraFunctions *f, const QSize &size);
    GLuint compile(QOpenGLExtraFunctions *f, const QByteArray &vs, const QByteArray &fs);
    VideoFrame pickFrame();
    void adaptPhase(qint64 slackNs);
    void acceptFrame(QOpenGLExtraFunctions *f, VideoFrame frame);
    void dropFrame();
    bool importNvmm(QOpenGLExtraFunctions *f);
    void uploadPlanes(QOpenGLExtraFunctions *f);

    QQuickWindow *m_window;
    Params m_params;

    VideoFrame m_frame;           // 지금 화면에 있는 프레임 (다음 프레임이 올 때까지 보관)
    GstBuffer *m_mappedBuffer = nullptr;
    GstMapInfo m_map{};
    EGLImageKHR m_image = EGL_NO_IMAGE_KHR;
    EGLDisplay m_imageDisplay = EGL_NO_DISPLAY;
    bool m_nvHelperImage = false;
    bool m_ready = false;
    int m_fmt = 0;

    GLuint m_progExternal = 0, m_progPlanar = 0;
    GLuint m_texExternal = 0;
    GLuint m_tex[3] = {0, 0, 0};
    GLuint m_vao = 0, m_vbo = 0;
    GLuint m_fbo = 0, m_fboTex = 0;
    QSize m_fboSize;
    YuvMatrix m_yuv = matrixFor(0.2126, 0.0722);
    float m_offset[3] = {0, 0, 0};
    float m_scale[3] = {1, 1, 1};

    // 프레임 선택 시점 조정 (pickFrame 참고)
    qint64 m_phaseAdj = 0;              // 판정 시각 보정 (±vsync/2)
    QList<qint64> m_slacks;             // 최근 프레임들의 (판정 시각 − 보여야 할 시각)
    QElapsedTimer m_sinceNewFrame;      // 마지막으로 새 프레임을 보여 준 뒤 지난 시간
    bool m_dirty = true;                // FBO를 다시 그려야 하는지 (새 프레임·크기·회전·HDR 변경)
    bool m_continuous = false;          // 이번 프레임 뒤에 곧바로 다음 프레임을 그리는지
    qint64 m_lastSwapNs = 0;            // 마지막 화면 교체가 끝난 시각 (단조 시계)
};

GLuint VideoRenderer::compile(QOpenGLExtraFunctions *f, const QByteArray &vs, const QByteArray &fs)
{
    auto shader = [&](GLenum type, const QByteArray &src) {
        GLuint s = f->glCreateShader(type);
        const char *p = src.constData();
        f->glShaderSource(s, 1, &p, nullptr);
        f->glCompileShader(s);
        GLint ok = 0;
        f->glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
        if (!ok) {
            char log[2048];
            f->glGetShaderInfoLog(s, sizeof log, nullptr, log);
            qCWarning(lcVideo) << "셰이더 컴파일 실패:" << log;
        }
        return s;
    };
    GLuint p = f->glCreateProgram();
    GLuint v = shader(GL_VERTEX_SHADER, vs), fr = shader(GL_FRAGMENT_SHADER, fs);
    f->glAttachShader(p, v);
    f->glAttachShader(p, fr);
    f->glBindAttribLocation(p, 0, "a_pos");
    f->glBindAttribLocation(p, 1, "a_tex");
    f->glLinkProgram(p);
    GLint ok = 0;
    f->glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[2048];
        f->glGetProgramInfoLog(p, sizeof log, nullptr, log);
        qCWarning(lcVideo) << "셰이더 링크 실패:" << log;
        f->glDeleteProgram(p);
        p = 0;
    }
    f->glDeleteShader(v);
    f->glDeleteShader(fr);
    return p;
}

bool VideoRenderer::ensurePrograms(QOpenGLExtraFunctions *f)
{
    if (m_progPlanar)
        return true;
    m_progExternal = compile(f, kVertex, QByteArray(kFragExternal) + kToneMap + kFragExternalMain);
    m_progPlanar = compile(f, kVertex, QByteArray(kFragPlanar) + kToneMap + kFragPlanarMain);
    f->glGenTextures(1, &m_texExternal);
    f->glGenTextures(3, m_tex);
    f->glGenVertexArrays(1, &m_vao);
    f->glGenBuffers(1, &m_vbo);
    for (GLuint t : m_tex) {
        f->glBindTexture(GL_TEXTURE_2D, t);
        f->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        f->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        f->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        f->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    }
    return m_progPlanar != 0;
}

void VideoRenderer::dropFrame()
{
    if (m_image != EGL_NO_IMAGE_KHR) {
#ifdef JVP_HAVE_NVMM
        if (m_nvHelperImage && m_mappedBuffer) {
            NvBufSurfaceUnMapEglImage(reinterpret_cast<NvBufSurface *>(m_map.data), 0);
        } else
#endif
        {
            static auto destroy = reinterpret_cast<PFNEGLDESTROYIMAGEKHRPROC>(eglGetProcAddress("eglDestroyImageKHR"));
            if (destroy)
                destroy(m_imageDisplay, m_image);
        }
        m_image = EGL_NO_IMAGE_KHR;
    }
    if (m_mappedBuffer) {
        gst_buffer_unmap(m_mappedBuffer, &m_map);
        m_mappedBuffer = nullptr;
    }
    if (m_frame.sample) {
        gst_sample_unref(m_frame.sample);
        m_frame = {};
    }
    m_ready = false;
}

bool VideoRenderer::importNvmm(QOpenGLExtraFunctions *f)
{
#ifdef JVP_HAVE_NVMM
    GstBuffer *buf = gst_sample_get_buffer(m_frame.sample);
    if (!buf || !gst_buffer_map(buf, &m_map, GST_MAP_READ))
        return false;
    m_mappedBuffer = buf;
    auto *surf = reinterpret_cast<NvBufSurface *>(m_map.data);
    if (!surf || surf->numFilled < 1)
        return false;
    const NvBufSurfaceParams &p = surf->surfaceList[0];

    static auto createImage = reinterpret_cast<PFNEGLCREATEIMAGEKHRPROC>(eglGetProcAddress("eglCreateImageKHR"));
    static auto targetTexture =
        reinterpret_cast<PFNGLEGLIMAGETARGETTEXTURE2DOESPROC>(eglGetProcAddress("glEGLImageTargetTexture2DOES"));
    // 1) Qt가 쓰는 EGL 디스플레이에 dma-buf로 직접 가져오기 (복사 없음)
    m_imageDisplay = eglGetCurrentDisplay();
    if (createImage && p.layout == NVBUF_LAYOUT_PITCH) {
        const EGLint attrs[] = {EGL_WIDTH, EGLint(p.width), EGL_HEIGHT, EGLint(p.height),
                                EGL_LINUX_DRM_FOURCC_EXT, EGLint(DRM_FORMAT_ABGR8888),
                                EGL_DMA_BUF_PLANE0_FD_EXT, EGLint(p.bufferDesc),
                                EGL_DMA_BUF_PLANE0_OFFSET_EXT, EGLint(p.planeParams.offset[0]),
                                EGL_DMA_BUF_PLANE0_PITCH_EXT, EGLint(p.planeParams.pitch[0]), EGL_NONE};
        m_image = createImage(m_imageDisplay, EGL_NO_CONTEXT, EGL_LINUX_DMA_BUF_EXT, nullptr, attrs);
        m_nvHelperImage = false;
    }
    // 2) 안 되면 Jetson 도우미 함수
    if (m_image == EGL_NO_IMAGE_KHR && NvBufSurfaceMapEglImage(surf, 0) == 0) {
        m_image = surf->surfaceList[0].mappedAddr.eglImage;
        m_nvHelperImage = true;
    }
    if (m_image == EGL_NO_IMAGE_KHR || !targetTexture)
        return false;
    f->glActiveTexture(GL_TEXTURE0);
    f->glBindTexture(GL_TEXTURE_EXTERNAL_OES, m_texExternal);
    f->glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    f->glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    targetTexture(GL_TEXTURE_EXTERNAL_OES, m_image);
    return f->glGetError() == GL_NO_ERROR;
#else
    Q_UNUSED(f)
    return false;
#endif
}

void VideoRenderer::uploadPlanes(QOpenGLExtraFunctions *f)
{
    GstVideoInfo info;
    GstVideoFrame vf;
    if (!gst_video_info_from_caps(&info, gst_sample_get_caps(m_frame.sample)))
        return;
    if (!gst_video_frame_map(&vf, &info, gst_sample_get_buffer(m_frame.sample), GST_MAP_READ))
        return;
    auto upload = [&](int unit, int plane, GLenum internalFormat, GLenum format, int bpp) {
        f->glActiveTexture(GL_TEXTURE0 + unit);
        f->glBindTexture(GL_TEXTURE_2D, m_tex[unit]);
        const int w = GST_VIDEO_FRAME_COMP_WIDTH(&vf, plane == 0 ? 0 : 1);
        const int h = GST_VIDEO_FRAME_COMP_HEIGHT(&vf, plane == 0 ? 0 : 1);
        const int stride = GST_VIDEO_FRAME_PLANE_STRIDE(&vf, plane);
        f->glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        f->glPixelStorei(GL_UNPACK_ROW_LENGTH, stride / bpp);
        f->glTexImage2D(GL_TEXTURE_2D, 0, internalFormat, w, h, 0, format, GL_UNSIGNED_BYTE,
                        GST_VIDEO_FRAME_PLANE_DATA(&vf, plane));
        f->glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
    };
    switch (m_frame.format) {
    case FrameFormat::Rgba:
        m_fmt = 0;
        upload(0, 0, GL_RGBA, GL_RGBA, 4);
        break;
    case FrameFormat::I420:
        m_fmt = 1;
        upload(0, 0, GL_LUMINANCE, GL_LUMINANCE, 1);
        upload(1, 1, GL_LUMINANCE, GL_LUMINANCE, 1);
        upload(2, 2, GL_LUMINANCE, GL_LUMINANCE, 1);
        break;
    case FrameFormat::Nv12:
        m_fmt = 2;
        upload(0, 0, GL_LUMINANCE, GL_LUMINANCE, 1);
        upload(1, 1, GL_LUMINANCE_ALPHA, GL_LUMINANCE_ALPHA, 2);
        break;
    default:
        break;
    }
    // 색 행렬과 범위: caps의 colorimetry를 따릅니다.
    const GstVideoColorimetry &c = info.colorimetry;
    double kr = 0.2126, kb = 0.0722;
    gst_video_color_matrix_get_Kr_Kb(c.matrix, &kr, &kb);
    m_yuv = matrixFor(kr, kb);
    if (c.range == GST_VIDEO_COLOR_RANGE_0_255) {
        m_offset[0] = 0.f; m_offset[1] = m_offset[2] = 128.f / 255.f;
        m_scale[0] = m_scale[1] = m_scale[2] = 1.f;
    } else {
        m_offset[0] = 16.f / 255.f; m_offset[1] = m_offset[2] = 128.f / 255.f;
        m_scale[0] = 255.f / 219.f; m_scale[1] = m_scale[2] = 255.f / 224.f;
    }
    gst_video_frame_unmap(&vf);
}

void VideoRenderer::acceptFrame(QOpenGLExtraFunctions *f, VideoFrame frame)
{
    dropFrame();
    m_frame = frame;
    m_dirty = true;
    if (frame.format == FrameFormat::NvmmRgba) {
        m_ready = importNvmm(f);
        if (!m_ready)
            qCWarning(lcVideo) << "NVMM 프레임을 GL로 가져오지 못했습니다";
    } else if (frame.format != FrameFormat::None) {
        uploadPlanes(f);
        m_ready = true;
    }
    if (m_ready && m_params.bridge)
        m_params.bridge->markRendered();
}

void VideoRenderer::ensureFbo(QOpenGLExtraFunctions *f, const QSize &size)
{
    if (m_fbo && size == m_fboSize)
        return;
    if (!m_fbo) {
        f->glGenFramebuffers(1, &m_fbo);
        f->glGenTextures(1, &m_fboTex);
    }
    m_fboSize = size;
    m_dirty = true;
    f->glBindTexture(GL_TEXTURE_2D, m_fboTex);
    f->glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, size.width(), size.height(), 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    f->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    f->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    f->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    f->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    f->glBindFramebuffer(GL_FRAMEBUFFER, m_fbo);
    f->glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, m_fboTex, 0);
}

void VideoRenderer::render()
{
    QOpenGLContext *ctx = QOpenGLContext::currentContext();
    if (!ctx || !m_params.bridge)
        return;
    m_window->beginExternalCommands();
    QOpenGLExtraFunctions *f = ctx->extraFunctions();
    GLint prevFbo = 0;
    f->glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prevFbo);
    if (ensurePrograms(f)) {
        VideoFrame next = pickFrame();
        if (next.sample)
            acceptFrame(f, next);
    }
    const QSize target = m_params.targetSize;
    const bool external = m_frame.format == FrameFormat::NvmmRgba;
    const GLuint prog = external ? m_progExternal : m_progPlanar;
    if (!target.isEmpty() && target != m_fboSize)
        ensureFbo(f, target);
    // 새 프레임이 없는 vsync에는 FBO에 있는 그림을 그대로 씁니다 (매 vsync 4K 텍스처를 다시 그리지 않게).
    if (m_dirty && m_ready && prog && !target.isEmpty()) {
        m_dirty = false;
        f->glBindFramebuffer(GL_FRAMEBUFFER, m_fbo);
        f->glViewport(0, 0, target.width(), target.height());

        // 회전·반전: 결과 텍스처의 네 모서리에 대응하는 원본 좌표 (원본은 위쪽이 v=0).
        // Qt는 텍스처의 첫 행(GL y=-1)을 화면 위쪽으로 쓰므로, 결과 텍스처 행 순서 = 화면 위→아래.
        // 순서: (텍스처 첫 행 왼쪽, 첫 행 오른쪽, 마지막 행 왼쪽, 마지막 행 오른쪽) = 화면 (왼위, 오위, 왼아래, 오아래)
        static const QHash<QString, std::array<float, 8>> kTex = {
            {"identity", {0, 0, 1, 0, 0, 1, 1, 1}}, {"horiz", {1, 0, 0, 0, 1, 1, 0, 1}},
            {"vert", {0, 1, 1, 1, 0, 0, 1, 0}},     {"180", {1, 1, 0, 1, 1, 0, 0, 0}},
            {"90r", {0, 1, 0, 0, 1, 1, 1, 0}},      {"90l", {1, 0, 1, 1, 0, 0, 0, 1}},
        };
        const auto tex = kTex.value(m_params.rotation, kTex.value("identity"));
        const float verts[] = {-1, -1, tex[0], tex[1], 1, -1, tex[2], tex[3],
                               -1, 1,  tex[4], tex[5], 1, 1,  tex[6], tex[7]};
        QMatrix4x4 identity;

        f->glUseProgram(prog);
        f->glUniformMatrix4fv(f->glGetUniformLocation(prog, "u_mvp"), 1, GL_FALSE, identity.constData());
        f->glUniform1f(f->glGetUniformLocation(prog, "u_hdr"), float(m_params.hdr));
        f->glUniform1f(f->glGetUniformLocation(prog, "u_fixm"), m_params.fixm ? 1.f : 0.f);
        if (external) {
            f->glActiveTexture(GL_TEXTURE0);
            f->glBindTexture(GL_TEXTURE_EXTERNAL_OES, m_texExternal);
            f->glUniform1i(f->glGetUniformLocation(prog, "u_tex0"), 0);
        } else {
            for (int i = 0; i < 3; ++i) {
                f->glActiveTexture(GL_TEXTURE0 + i);
                f->glBindTexture(GL_TEXTURE_2D, m_tex[i]);
            }
            f->glUniform1i(f->glGetUniformLocation(prog, "u_tex0"), 0);
            f->glUniform1i(f->glGetUniformLocation(prog, "u_tex1"), 1);
            f->glUniform1i(f->glGetUniformLocation(prog, "u_tex2"), 2);
            f->glUniform1f(f->glGetUniformLocation(prog, "u_fmt"), float(m_fmt));
            f->glUniformMatrix3fv(f->glGetUniformLocation(prog, "u_yuv"), 1, GL_FALSE, m_yuv.m);
            f->glUniform3fv(f->glGetUniformLocation(prog, "u_offset"), 1, m_offset);
            f->glUniform3fv(f->glGetUniformLocation(prog, "u_scale"), 1, m_scale);
        }
        f->glBindVertexArray(m_vao);
        f->glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
        f->glBufferData(GL_ARRAY_BUFFER, sizeof verts, verts, GL_STREAM_DRAW);
        f->glEnableVertexAttribArray(0);
        f->glEnableVertexAttribArray(1);
        f->glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float), nullptr);
        f->glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float), reinterpret_cast<void *>(2 * sizeof(float)));
        f->glDisable(GL_BLEND);
        f->glDisable(GL_DEPTH_TEST);
        f->glDisable(GL_STENCIL_TEST);
        f->glDisable(GL_SCISSOR_TEST);
        f->glDisable(GL_CULL_FACE);
        f->glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        f->glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
        f->glBindVertexArray(0);
        f->glBindBuffer(GL_ARRAY_BUFFER, 0);
        f->glActiveTexture(GL_TEXTURE0);
        static bool reported = false;
        if (!reported) {
            reported = true;
            if (GLenum err = f->glGetError())
                qCWarning(lcVideo) << "GL 오류" << Qt::hex << err;
        }
    }
    f->glBindFramebuffer(GL_FRAMEBUFFER, GLuint(prevFbo));
    m_window->endExternalCommands();
    // 재생 중에는 vsync마다 다시 그려 프레임을 제때 바꿉니다 (렌더 스레드에서 부르면 GUI 동기화 없이 다시 그림).
    // 새 프레임이 한동안 없으면(일시정지·끝) 멈추고, 새 프레임이 오면 frameReady → update()로 다시 시작합니다.
    m_continuous = m_params.bridge->hasPending() || (m_sinceNewFrame.isValid() && m_sinceNewFrame.elapsed() < 250);
    if (m_continuous)
        m_window->update();
}

// NVIDIA EGL은 화면 교체(swap)에서 vsync를 기다리는 동안 CPU를 계속 돌립니다 (매 vsync 그리면 코어 하나 100%).
// 다음 vsync 직전까지 잠들어 두어 드라이버가 기다리는 시간을 줄입니다.
// swap이 기다리지 않는 환경(vsync 없는 가상 화면 등)에서도 이 덕분에 초당 화면 주기만큼만 그립니다.
void VideoRenderer::paceBeforeSwap()
{
    if (!m_continuous || !m_lastSwapNs)
        return;
    constexpr qint64 kMarginNs = 2 * GST_MSECOND;   // 잠에서 깨는 지연을 감안한 여유
    const qint64 wake = m_lastSwapNs + m_params.vsyncNs - kMarginNs;
    const qint64 wait = wake - g_get_monotonic_time() * 1000;
    if (wait > 0 && wait < m_params.vsyncNs)
        g_usleep(gulong(wait / 1000));
}

// 다음 vsync에 보여야 할 프레임을 고릅니다.
// 이 렌더링 결과는 약 한 vsync 뒤에 화면에 나오므로 "지금 + vsync" 시점까지 보여야 할 프레임 중 가장 늦은 것.
// 24fps를 60Hz로 보이면 프레임의 절반이 vsync 경계에 정확히 걸려, 판정 시각이 1ms만 흔들려도
// 2:3 순서가 깨집니다 (끊겨 보임). 그래서 판정 시각을 프레임들이 경계에서 가장 멀어지는 쪽으로 옮깁니다.
VideoFrame VideoRenderer::pickFrame()
{
    GstClockTime now = 0;
    if (!m_params.bridge->runningTimeNow(&now))
        return m_params.bridge->takeFrame(std::nullopt);   // 일시정지·준비 중: 가장 최근 프레임 (탐색 미리보기)
    const qint64 target = qint64(now) + m_params.vsyncNs + m_phaseAdj;
    VideoFrame f = m_params.bridge->takeFrame(GstClockTime(qMax<qint64>(0, target)));
    if (f.sample) {
        m_sinceNewFrame.start();
        if (GST_CLOCK_TIME_IS_VALID(f.runningTime))
            adaptPhase(target - qint64(f.runningTime));
    }
    return f;
}

void VideoRenderer::adaptPhase(qint64 slackNs)
{
    const qint64 period = m_params.vsyncNs;
    if (slackNs < 0 || slackNs > 4 * period)
        return;   // 늦게 도착한 프레임 등은 판단에서 뺍니다
    m_slacks << slackNs % period;
    if (m_slacks.size() < 48)
        return;
    // 판정 시각을 adj만큼 옮기면 각 프레임의 여유는 (slack + adj) mod period가 됩니다.
    // 경계(0 또는 period)까지의 가장 작은 거리가 가장 커지는 adj를 찾습니다.
    auto margin = [&](qint64 adj) {
        qint64 worst = period;
        for (qint64 sl : std::as_const(m_slacks)) {
            const qint64 v = ((sl + adj) % period + period) % period;
            worst = qMin(worst, qMin(v, period - v));
        }
        return worst;
    };
    const qint64 current = margin(0);
    qint64 bestAdj = 0, best = current;
    for (qint64 adj = -period / 2; adj < period / 2; adj += period / 64) {
        if (const qint64 m = margin(adj); m > best) {
            best = m;
            bestAdj = adj;
        }
    }
    // 지금도 충분히 여유가 있으면 그대로 둡니다 (옮기는 순간 한 번은 순서가 바뀌므로).
    if (current < period / 4 && best > current + period / 16) {
        m_phaseAdj += bestAdj;
        m_phaseAdj = ((m_phaseAdj + period / 2) % period + period) % period - period / 2;
    }
    m_slacks.clear();
}

void VideoRenderer::releaseResources()
{
    dropFrame();
    QOpenGLContext *ctx = QOpenGLContext::currentContext();
    if (!ctx)
        return;
    QOpenGLExtraFunctions *f = ctx->extraFunctions();
    if (m_progExternal)
        f->glDeleteProgram(m_progExternal);
    if (m_progPlanar)
        f->glDeleteProgram(m_progPlanar);
    if (m_texExternal)
        f->glDeleteTextures(1, &m_texExternal);
    if (m_tex[0])
        f->glDeleteTextures(3, m_tex);
    if (m_fbo)
        f->glDeleteFramebuffers(1, &m_fbo);
    if (m_fboTex)
        f->glDeleteTextures(1, &m_fboTex);
    m_fbo = m_fboTex = 0;
    m_fboSize = {};
    if (m_vao)
        f->glDeleteVertexArrays(1, &m_vao);
    if (m_vbo)
        f->glDeleteBuffers(1, &m_vbo);
    m_vao = m_vbo = 0;
    m_progExternal = m_progPlanar = m_texExternal = 0;
    m_tex[0] = m_tex[1] = m_tex[2] = 0;
}

// 렌더러가 그린 FBO 텍스처를 화면에 올리는 노드
class VideoNode : public QSGSimpleTextureNode {
public:
    explicit VideoNode(QQuickWindow *window) : m_window(window), m_renderer(new VideoRenderer(window))
    {
        setOwnsTexture(true);
        setFiltering(QSGTexture::Linear);
        QObject::connect(window, &QQuickWindow::beforeRendering, m_renderer, [r = m_renderer] { r->render(); },
                         Qt::DirectConnection);
        QObject::connect(window, &QQuickWindow::afterRendering, m_renderer, [r = m_renderer] { r->paceBeforeSwap(); },
                         Qt::DirectConnection);
        QObject::connect(window, &QQuickWindow::frameSwapped, m_renderer, [r = m_renderer] { r->markSwapped(); },
                         Qt::DirectConnection);
    }
    ~VideoNode() override { delete m_renderer; }

    void sync(const VideoRenderer::Params &p, const QRectF &rect)
    {
        m_renderer->setParams(p);
        m_renderer->prepareTarget();
        setRect(rect);
        // 렌더러가 만든 FBO 텍스처가 바뀌었으면 Qt 텍스처로 감쌉니다.
        if (m_renderer->texture() && (m_renderer->texture() != m_wrapped || m_renderer->textureSize() != m_wrappedSize)) {
            m_wrapped = m_renderer->texture();
            m_wrappedSize = m_renderer->textureSize();
            setTexture(QNativeInterface::QSGOpenGLTexture::fromNative(m_wrapped, m_window, m_wrappedSize,
                                                                     QQuickWindow::TextureIsOpaque));
        }
    }
    bool ready() const { return m_renderer->hasFrame() && texture(); }

private:
    QQuickWindow *m_window;
    VideoRenderer *m_renderer;
    GLuint m_wrapped = 0;
    QSize m_wrappedSize;
};

} // namespace

VideoItem::VideoItem(QQuickItem *parent) : QQuickItem(parent)
{
    setFlag(ItemHasContents, true);
}

QObject *VideoItem::bridge() const { return m_bridge.data(); }

void VideoItem::setBridge(QObject *bridge)
{
    auto *b = qobject_cast<FrameBridge *>(bridge);
    if (b == m_bridge)
        return;
    if (m_bridge)
        disconnect(m_bridge, nullptr, this, nullptr);
    m_bridge = b;
    if (m_bridge) {
        connect(m_bridge, &FrameBridge::frameReady, this, &QQuickItem::update, Qt::QueuedConnection);
        connect(m_bridge, &FrameBridge::videoSizeChanged, this, [this](QSize s, double par) {
            m_videoSize = s.isEmpty() ? QSizeF() : QSizeF(s.width() * par, s.height());
            emit videoRectChanged();
            update();
        }, Qt::QueuedConnection);
    }
    emit bridgeChanged();
    update();
}

void VideoItem::setHdrMode(int mode)
{
    if (mode == m_hdrMode)
        return;
    m_hdrMode = mode;
    emit hdrChanged();
    update();
}

void VideoItem::setHdrMatrixFix(bool fix)
{
    if (fix == m_hdrFix)
        return;
    m_hdrFix = fix;
    emit hdrChanged();
    update();
}

void VideoItem::setOrientation(const QString &r)
{
    if (r == m_rotation)
        return;
    m_rotation = r;
    emit orientationChanged();
    emit videoRectChanged();
    update();
}

QRectF VideoItem::videoRect() const
{
    if (m_videoSize.isEmpty() || width() <= 0 || height() <= 0)
        return {};
    QSizeF vs = m_videoSize;
    if (m_rotation == QLatin1String("90r") || m_rotation == QLatin1String("90l"))
        vs.transpose();
    const qreal scale = qMin(width() / vs.width(), height() / vs.height());
    const QSizeF s(vs.width() * scale, vs.height() * scale);
    return QRectF((width() - s.width()) / 2, (height() - s.height()) / 2, s.width(), s.height());
}

void VideoItem::geometryChange(const QRectF &newGeometry, const QRectF &oldGeometry)
{
    QQuickItem::geometryChange(newGeometry, oldGeometry);
    emit videoRectChanged();
    update();
}

QSGNode *VideoItem::updatePaintNode(QSGNode *old, UpdatePaintNodeData *)
{
    auto *node = static_cast<VideoNode *>(old);
    const QRectF rect = videoRect();
    if (!m_bridge || rect.isEmpty()) {
        delete node;
        return nullptr;
    }
    if (!node)
        node = new VideoNode(window());
    const qreal dpr = window()->effectiveDevicePixelRatio();
    VideoRenderer::Params p;
    p.bridge = m_bridge;
    p.targetSize = (rect.size() * dpr).toSize();
    p.rotation = m_rotation;
    p.hdr = m_hdrMode;
    p.fixm = m_hdrFix;
    if (const QScreen *screen = window()->screen(); screen && screen->refreshRate() > 1)
        p.vsyncNs = qint64(1e9 / screen->refreshRate());
    node->sync(p, rect);
    if (!node->texture()) {
        delete node;   // GL 컨텍스트가 없는 드문 경우: 다음 동기화에서 다시
        QMetaObject::invokeMethod(this, &QQuickItem::update, Qt::QueuedConnection);
        return nullptr;
    }
    node->markDirty(QSGNode::DirtyMaterial);
    return node;
}

} // namespace jvp
