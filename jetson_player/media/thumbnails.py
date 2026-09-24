"""타임라인 hover 미리보기용 썸네일을 백그라운드에서 생성·캐시합니다 (NVDEC 하드웨어 디코딩).

영상 전체를 디코딩하지 않고 N개 지점만 키프레임 탐색으로 추출하므로 긴 4K 영상도 수 초 안에 끝납니다.
결과: ~/.cache/jetson_video_player/thumbs/<hash>/index.json + 000.jpg ...
"""
import hashlib
import json
import os
import threading
import time
from urllib.request import pathname2url

import numpy as np
from gi.repository import GdkPixbuf, GLib, Gst, GstPbutils

from ..storage import CACHE_DIR, atomic_write_json
from .scenes import detect_scene_changes, image_signature, scene_changes_from_diffs

THUMB_ROOT = os.path.join(CACHE_DIR, "thumbs")
THUMB_WIDTH = 160
INDEX_VERSION = 1


def thumbnail_cache_dir(path):
    try:
        st = os.stat(path)
        key = f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        key = os.path.abspath(path)
    return os.path.join(THUMB_ROOT, hashlib.sha1(key.encode("utf-8")).hexdigest()[:20])


def load_thumbnail_index(path):
    """캐시된 썸네일 인덱스 {"positions": [...], "files": [...], "scenes": [...]} 또는 None"""
    index_file = os.path.join(thumbnail_cache_dir(path), "index.json")
    try:
        with open(index_file, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") == INDEX_VERSION and data.get("complete"):
            data["dir"] = os.path.dirname(index_file)
            return data
    except (OSError, ValueError):
        pass
    return None


def sample_count(duration_ns):
    """영상 길이에 따른 썸네일 개수: 10초 간격, 최소 20장, 최대 120장"""
    return max(20, min(120, int(duration_ns / Gst.SECOND / 10)))


class ThumbnailJob:
    """한 영상의 썸네일 생성 작업. cancel()로 중단할 수 있습니다.

    on_progress(index_dict)는 일부가 준비될 때마다, on_done(index_dict)는 완료 시 메인 스레드에서 호출됩니다.
    """

    def __init__(self, path, on_progress=None, on_done=None):
        self.path = path
        self.on_progress = on_progress
        self.on_done = on_done
        self.cancelled = False
        self.thread = threading.Thread(target=self._run, daemon=True, name="thumbnails")

    def start(self):
        cached = load_thumbnail_index(self.path)
        if cached:
            if self.on_done:
                GLib.idle_add(lambda: (self.on_done(cached), False)[1])
            return
        self.thread.start()

    def cancel(self):
        self.cancelled = True

    # ---- 내부 -----------------------------------------------------------
    @staticmethod
    def _probe(uri):
        info = GstPbutils.Discoverer.new(5 * Gst.SECOND).discover_uri(uri)
        streams = info.get_video_streams()
        if not streams:
            return None
        v = streams[0]
        w, h = v.get_width(), v.get_height()
        par_n, par_d = v.get_par_num() or 1, v.get_par_denom() or 1
        return info.get_duration(), w * par_n / par_d, h

    def _build_pipeline(self, uri, thumb_h):
        mid_w, mid_h = THUMB_WIDTH * 2, thumb_h * 2
        conv = Gst.ElementFactory.find("nvvidconv")
        # NVDEC 출력(NVMM)을 nvvidconv로 줄인 뒤 CPU에서 최종 크기로 축소합니다. 없으면 일반 변환기 사용.
        head = (f"nvvidconv ! video/x-raw,format=RGBA,width={mid_w},height={mid_h} ! " if conv
                else "videoconvert ! ")
        desc = f"{head}videoscale ! videoconvert ! video/x-raw,format=RGBA,width={THUMB_WIDTH},height={thumb_h},pixel-aspect-ratio=1/1 ! appsink name=sink sync=false max-buffers=1"
        pb = Gst.ElementFactory.make("playbin", "thumbnailer")
        pb.set_property("uri", uri)
        vbin = Gst.parse_bin_from_description(desc, True)
        pb.set_property("video-sink", vbin)
        pb.set_property("audio-sink", Gst.ElementFactory.make("fakesink", None))
        pb.set_property("flags", 0x41 if conv else 0x01)  # video + native-video (NVMM 유지)
        return pb, vbin.get_by_name("sink")

    def _run(self):
        try:
            self._generate()
        except Exception as e:
            print(f"⚠️ 썸네일 생성 실패 ({os.path.basename(self.path)}): {e}")

    def _generate(self):
        uri = f"file://{pathname2url(os.path.abspath(self.path))}"
        probed = self._probe(uri)
        if not probed or self.cancelled:
            return
        duration, vw, vh = probed
        if duration <= 0 or not vw or not vh:
            return
        thumb_h = max(2, int(round(THUMB_WIDTH * vh / vw / 2)) * 2)

        out_dir = thumbnail_cache_dir(self.path)
        os.makedirs(out_dir, exist_ok=True)
        pb, sink = self._build_pipeline(uri, thumb_h)
        pb.set_state(Gst.State.PAUSED)
        if pb.get_state(10 * Gst.SECOND)[0] == Gst.StateChangeReturn.FAILURE:
            pb.set_state(Gst.State.NULL)
            print(f"⚠️ 썸네일 파이프라인 준비 실패: {os.path.basename(self.path)}")
            return

        n = sample_count(duration)
        positions, files, signatures = [], [], []
        started = time.time()
        try:
            for i in range(n):
                if self.cancelled:
                    break
                target = int(duration * (i + 0.5) / n)
                pb.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, target)
                pb.get_state(3 * Gst.SECOND)
                sample = sink.emit("try-pull-preroll", 2 * Gst.SECOND)
                if sample is None:
                    continue
                buf = sample.get_buffer()
                pts = buf.pts if buf.pts != Gst.CLOCK_TIME_NONE else target
                if positions and abs(pts - positions[-1]) < Gst.SECOND // 2:
                    continue  # 같은 키프레임으로 다시 탐색된 경우
                data = buf.extract_dup(0, buf.get_size())
                fname = f"{len(files):03d}.jpg"
                pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(data), GdkPixbuf.Colorspace.RGB, True, 8,
                                                         THUMB_WIDTH, thumb_h, THUMB_WIDTH * 4)
                pixbuf.savev(os.path.join(out_dir, fname), "jpeg", ["quality"], ["80"])
                positions.append(pts)
                files.append(fname)
                signatures.append(image_signature(data, THUMB_WIDTH, thumb_h))
                if self.on_progress and len(files) % 10 == 0:
                    snapshot = {"dir": out_dir, "positions": list(positions), "files": list(files), "scenes": []}
                    GLib.idle_add(lambda s=snapshot: (self.on_progress(s), False)[1])
                time.sleep(0.02)  # 재생 중인 영상의 디코딩/IO에 양보
        finally:
            # 예외가 나도 파이프라인을 정리해 NVDEC 디코더 세션을 반납합니다.
            pb.set_state(Gst.State.NULL)
        if self.cancelled or not files:
            return

        # 추출 순서와 무관하게 시간순 정렬 후 장면 전환 검출
        order = sorted(range(len(positions)), key=lambda k: positions[k])
        positions = [positions[k] for k in order]
        files = [files[k] for k in order]
        signatures = [signatures[k] for k in order]
        scenes = detect_scene_changes(signatures, positions, duration)
        index = {"version": INDEX_VERSION, "complete": True, "duration": duration,
                 "positions": positions, "files": files, "scenes": scenes}
        atomic_write_json(os.path.join(out_dir, "index.json"), index)
        print(f"🖼️ [썸네일] {len(files)}장, 장면 전환 {len(scenes)}곳 ({time.time() - started:.1f}초): {os.path.basename(self.path)}")
        index["dir"] = out_dir
        if self.on_done:
            GLib.idle_add(lambda: (self.on_done(index), False)[1])


class SceneAnalysisJob:
    """[사용자 요청 시] 모든 프레임을 16x9 크기로 하드웨어 디코딩해 장면 전환을 프레임 단위로 찾습니다.

    비참조 프레임은 건너뛰어(skip-frames=1) 4K 영상도 실시간의 약 10배 속도로 분석합니다.
    결과는 썸네일 인덱스의 "scenes_precise"에 저장되어 다음부터 즉시 사용됩니다.
    on_progress(0~1), on_done(scenes | None) 은 메인 스레드에서 호출됩니다.
    """

    def __init__(self, path, on_progress=None, on_done=None):
        self.path = path
        self.on_progress = on_progress
        self.on_done = on_done
        self.cancelled = False
        self.progress = 0.0
        self._loop = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="scene-analysis")

    def start(self):
        self.thread.start()

    def cancel(self):
        self.cancelled = True
        if self._loop is not None:
            self._loop.quit()

    def _run(self):
        scenes = None
        try:
            scenes = self._analyze()
        except Exception as e:
            print(f"⚠️ 장면 분석 실패: {e}")
        if self.on_done:
            GLib.idle_add(lambda: (self.on_done(None if self.cancelled else scenes), False)[1])

    def _analyze(self):
        uri = f"file://{pathname2url(os.path.abspath(self.path))}"
        has_nv = Gst.ElementFactory.find("nvvidconv") is not None
        head = "nvvidconv ! video/x-raw,format=RGBA,width=320,height=180 ! " if has_nv else "videoconvert ! "
        desc = f"{head}videoscale ! videoconvert ! video/x-raw,format=RGBA,width=16,height=9 ! appsink name=sink sync=false emit-signals=true"
        pb = Gst.ElementFactory.make("playbin", "scene_analyzer")
        pb.set_property("uri", uri)
        vbin = Gst.parse_bin_from_description(desc, True)
        pb.set_property("video-sink", vbin)
        pb.set_property("audio-sink", Gst.ElementFactory.make("fakesink", None))
        pb.set_property("flags", 0x41 if has_nv else 0x01)

        def on_element(_bin, _sub, element):
            factory = element.get_factory()
            if factory and factory.get_name() == "nvv4l2decoder" and element.find_property("skip-frames"):
                element.set_property("skip-frames", 1)   # 비참조 프레임 건너뛰기
        pb.connect("deep-element-added", on_element)

        diffs, positions = [], []
        state = {"prev": None, "duration": 0, "last_report": 0.0}

        def on_sample(sink):
            sample = sink.emit("pull-sample")
            buf = sample.get_buffer()
            sig = np.frombuffer(buf.extract_dup(0, buf.get_size()), dtype=np.uint8).reshape(9, 16, 4)[:, :, :3].astype(np.float32)
            if state["prev"] is not None:
                diffs.append(float(np.abs(sig - state["prev"]).mean()))
                positions.append(buf.pts)
            state["prev"] = sig
            if state["duration"] > 0 and buf.pts != Gst.CLOCK_TIME_NONE:
                self.progress = min(1.0, buf.pts / state["duration"])
                if self.on_progress and self.progress - state["last_report"] >= 0.02:
                    state["last_report"] = self.progress
                    GLib.idle_add(lambda p=self.progress: (self.on_progress(p), False)[1])
            return Gst.FlowReturn.FLUSHING if self.cancelled else Gst.FlowReturn.OK

        vbin.get_by_name("sink").connect("new-sample", on_sample)
        ctx = GLib.MainContext.new()
        ctx.push_thread_default()
        loop = self._loop = GLib.MainLoop.new(ctx, False)
        bus = pb.get_bus()
        bus.add_signal_watch()
        error = []

        def on_message(_bus, msg):
            if msg.type == Gst.MessageType.EOS:
                loop.quit()
            elif msg.type == Gst.MessageType.ERROR:
                error.append(msg.parse_error()[0].message)
                loop.quit()
            elif msg.type == Gst.MessageType.ASYNC_DONE and state["duration"] == 0:
                ok, dur = pb.query_duration(Gst.Format.TIME)
                if ok:
                    state["duration"] = dur
        bus.connect("message", on_message)
        started = time.time()
        try:
            pb.set_state(Gst.State.PLAYING)
            loop.run()
        finally:
            pb.set_state(Gst.State.NULL)   # 예외가 나도 NVDEC 디코더 세션 반납
            bus.remove_signal_watch()
            ctx.pop_thread_default()
        if self.cancelled:
            return None
        if error:
            raise RuntimeError(error[0])

        duration = state["duration"] or (positions[-1] if positions else 0)
        scenes = scene_changes_from_diffs(diffs, positions, duration, sensitivity=6.0,
                                          min_gap_ns=max(3 * Gst.SECOND, duration // 100), max_scenes=80)
        print(f"🎬 [정밀 장면 분석] 프레임 {len(diffs) + 1}개, 장면 전환 {len(scenes)}곳 ({time.time() - started:.1f}초)")
        index_file = os.path.join(thumbnail_cache_dir(self.path), "index.json")
        try:
            with open(index_file, encoding="utf-8") as f:
                index = json.load(f)
            index["scenes_precise"] = scenes
            atomic_write_json(index_file, index)
        except (OSError, ValueError):
            pass
        return scenes
