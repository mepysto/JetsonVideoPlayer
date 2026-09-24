"""진행바(타임라인): 마우스 hover 미리보기(시각 + 썸네일), 남은 시간 표시 전환, 북마크/구간/챕터 눈금"""
import bisect
import os
from collections import OrderedDict

from gi.repository import GdkPixbuf, Gdk, GLib, Gst, Gtk

from ..media.thumbnails import SceneAnalysisJob, ThumbnailJob
from ..settings import settings
from ..storage import bookmark_cache


class TimelineMixin:
    # ---- hover 미리보기 ---------------------------------------------------
    def setup_timeline_interactions(self, scale):
        """진행바에 hover 미리보기 팝오버를 연결합니다 (일반/전체화면 진행바 공용)."""
        scale.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        scale.connect("motion-notify-event", self.on_timeline_motion)
        scale.connect("leave-notify-event", self.on_timeline_leave)

        pop = Gtk.Popover(relative_to=scale)
        pop.set_modal(False)
        pop.set_position(Gtk.PositionType.TOP)
        pop.set_transitions_enabled(False)
        pop.get_style_context().add_class("timeline-preview")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        image = Gtk.Image()
        image.set_no_show_all(True)
        label = Gtk.Label()
        label.get_style_context().add_class("timeline-preview-time")
        box.pack_start(image, False, False, 0)
        box.pack_start(label, False, False, 0)
        pop.add(box)
        box.show_all()
        scale.timeline_preview = (pop, image, label)

    @staticmethod
    def _scale_ratio_at(scale, x):
        alloc = scale.get_allocation()
        if alloc.width <= 0:
            return None
        return max(0.0, min(1.0, x / alloc.width))

    def on_timeline_motion(self, scale, event):
        preview = getattr(scale, "timeline_preview", None)
        if not preview or self.duration_ns <= 0:
            return False
        pop, image, label = preview
        ratio = self._scale_ratio_at(scale, event.x)
        if ratio is None:
            return False
        target_ns = int(self.duration_ns * ratio)
        text = self.format_time(target_ns)
        chapter = self.chapter_title_at(target_ns) if hasattr(self, "chapter_title_at") else None
        if chapter:
            text = f"{text}  ·  {chapter}"
        label.set_text(text)

        pixbuf = self.get_thumbnail_at(target_ns) if hasattr(self, "get_thumbnail_at") else None
        if pixbuf is not None:
            image.set_from_pixbuf(pixbuf)
            image.show()
        else:
            image.hide()

        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(event.x), 0, 1, 1
        pop.set_pointing_to(rect)
        if not pop.get_visible():
            pop.show()
        return False

    def on_timeline_leave(self, scale, _event):
        preview = getattr(scale, "timeline_preview", None)
        if preview:
            preview[0].hide()
        return False

    def hide_timeline_previews(self):
        for scale in (getattr(self, "progress_scale", None), getattr(self, "fs_progress_scale", None)):
            preview = getattr(scale, "timeline_preview", None) if scale else None
            if preview:
                preview[0].hide()

    # ---- 남은 시간 / 전체 시간 전환 ----------------------------------------
    def make_time_toggle(self, label):
        """시간 라벨을 클릭하면 전체 길이와 남은 시간 표시를 전환하도록 감쌉니다."""
        box = Gtk.EventBox()
        box.add(label)
        box.set_tooltip_text("클릭: 전체 길이 / 남은 시간 표시 전환")
        box.connect("button-press-event", lambda _w, _e: (self.toggle_time_display(), True)[1])
        return box

    def toggle_time_display(self):
        settings.set("time_display_remaining", not settings.get("time_display_remaining"))
        self.update_duration_labels(self.last_known_pos_ns)

    def update_duration_labels(self, position_ns):
        if self.duration_ns <= 0:
            return
        if settings.get("time_display_remaining"):
            text = "-" + self.format_time(max(0, self.duration_ns - position_ns))
        else:
            text = self.format_time(self.duration_ns)
        for lbl in (getattr(self, "duration_label", None), getattr(self, "fs_duration_label", None)):
            if lbl:
                lbl.set_text(text)

    # ---- 눈금: 북마크 / A-B 구간 / 챕터 -------------------------------------
    def refresh_timeline_marks(self):
        """진행바에 북마크(▾), A-B 구간, 챕터 위치를 눈금으로 표시합니다."""
        scales = [s for s in (getattr(self, "progress_scale", None), getattr(self, "fs_progress_scale", None)) if s]
        for scale in scales:
            scale.clear_marks()
        if self.duration_ns <= 0 or not self.playlist or not (0 <= self.current_index < len(self.playlist)):
            return
        positions = []
        for bm in bookmark_cache.get(self.playlist[self.current_index]):
            positions.append(bm.get("position_ns", 0))
        for chapter_ns, _title in getattr(self, "chapters", []):
            if chapter_ns > 0:
                positions.append(chapter_ns)
        if self.ab_repeat_a is not None:
            positions.append(self.ab_repeat_a)
        if self.ab_repeat_b is not None:
            positions.append(self.ab_repeat_b)
        for scale in scales:
            for pos in positions:
                scale.add_mark(min(100.0, pos * 100.0 / self.duration_ns), Gtk.PositionType.TOP, None)

    # ---- 썸네일 ---------------------------------------------------------
    def start_thumbnails(self, path):
        """현재 영상의 썸네일/장면 분석을 백그라운드로 시작합니다 (재생 시작 2초 후)."""
        for job_name in ("thumb_job", "scene_job"):
            job = getattr(self, job_name, None)
            if job:
                job.cancel()
            setattr(self, job_name, None)
        self.thumb_index = None
        self.thumb_cache = OrderedDict()
        self.scene_chapters = []
        if not path or path.startswith(("http://", "https://")) or not os.path.isfile(path):
            return

        def begin():
            if not self.playlist or self.playlist[self.current_index] != path:
                return False
            self.thumb_job = ThumbnailJob(path, on_progress=self._on_thumbnails, on_done=self._on_thumbnails)
            self.thumb_job.start()
            return False
        GLib.timeout_add(2000, begin)

    def _on_thumbnails(self, index):
        job = getattr(self, "thumb_job", None)
        if job is not None and job.cancelled:
            return
        self.thumb_index = index
        self._set_scene_chapters(index.get("scenes_precise") or index.get("scenes") or [])

    def _set_scene_chapters(self, scenes):
        if scenes:
            self.scene_chapters = [(0, "시작")] + [(pos, f"장면 {n}") for n, pos in enumerate(scenes, 1)]
            self.refresh_timeline_marks()

    def start_scene_analysis(self):
        """[요청 시] 전체 프레임을 분석해 정확한 장면 전환 챕터를 만듭니다."""
        if getattr(self, "scene_job", None) and self.scene_job.thread.is_alive():
            return
        if not self.playlist:
            return
        path = self.playlist[self.current_index]
        if path.startswith(("http://", "https://")):
            return

        def progress(p):
            self.show_osd(f"🔍 장면 분석 중 {p * 100:.0f}%", duration_sec=1.5)

        def done(scenes):
            self.scene_job = None
            if scenes is None:
                self.show_osd("🔍 장면 분석을 취소했습니다.")
                return
            if not self.playlist or self.playlist[self.current_index] != path:
                return
            self.scene_chapters = []
            self._set_scene_chapters(scenes)
            self.show_osd(f"🔍 장면 분석 완료: {len(scenes)}곳 (K로 목록 보기)", duration_sec=3.0)

        self.scene_job = SceneAnalysisJob(path, on_progress=progress, on_done=done)
        self.scene_job.start()
        self.show_osd("🔍 정밀 장면 분석을 시작합니다 (백그라운드)", duration_sec=2.0)

    def cancel_scene_analysis(self):
        job = getattr(self, "scene_job", None)
        if job:
            job.cancel()

    def get_thumbnail_at(self, position_ns):
        index = getattr(self, "thumb_index", None)
        if not index or not index.get("positions"):
            return None
        positions = index["positions"]
        i = bisect.bisect_right(positions, position_ns) - 1
        i = max(0, min(len(positions) - 1, i))
        # 다음 썸네일이 더 가까우면 그것을 사용
        if i + 1 < len(positions) and abs(positions[i + 1] - position_ns) < abs(position_ns - positions[i]):
            i += 1
        path = os.path.join(index["dir"], index["files"][i])
        cache = self.thumb_cache
        if path in cache:
            cache.move_to_end(path)
            return cache[path]
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except GLib.Error:
            return None
        cache[path] = pixbuf
        if len(cache) > 64:
            cache.popitem(last=False)
        return pixbuf

    # ---- 챕터 (컨테이너 TOC 우선, 없으면 자동 장면 분석) -------------------
    @property
    def chapters(self):
        return getattr(self, "toc_chapters", None) or getattr(self, "scene_chapters", [])

    def handle_toc_message(self, message):
        """MKV/MP4 챕터(TOC)를 읽어 챕터 목록을 만듭니다."""
        toc, _updated = message.parse_toc()
        found = []

        def visit(entries):
            for entry in entries:
                if entry.get_entry_type() == Gst.TocEntryType.CHAPTER:
                    ok, start, _stop = entry.get_start_stop_times()
                    title = None
                    tags = entry.get_tags()
                    if tags:
                        ok_t, title = tags.get_string(Gst.TAG_TITLE)
                        title = title if ok_t else None
                    if ok and start >= 0:
                        found.append((start, title or f"챕터 {len(found) + 1}"))
                visit(entry.get_sub_entries())

        visit(toc.get_entries())
        if found:
            self.toc_chapters = sorted(found)
            print(f"📑 [챕터] {len(found)}개 (컨테이너 TOC)")
            self.refresh_timeline_marks()

    def chapter_title_at(self, position_ns):
        chapters = self.chapters
        if not chapters:
            return None
        starts = [c[0] for c in chapters]
        i = bisect.bisect_right(starts, position_ns) - 1
        return chapters[i][1] if i >= 0 else None

    def show_chapters_menu(self, event=None):
        """챕터/장면 목록 메뉴: 선택하면 해당 위치로 이동합니다 (단축키 K)."""
        menu = Gtk.Menu()
        chapters = self.chapters
        job = getattr(self, "scene_job", None)
        if job and job.thread.is_alive():
            item = Gtk.MenuItem(label=f"⏹ 장면 분석 취소 ({job.progress * 100:.0f}% 진행)")
            item.connect("activate", lambda _i: self.cancel_scene_analysis())
        else:
            has_precise = bool((getattr(self, "thumb_index", None) or {}).get("scenes_precise"))
            item = Gtk.MenuItem(label="🔍 정밀 장면 분석 다시 실행" if has_precise else "🔍 정밀 장면 분석 (모든 프레임, 백그라운드)")
            item.connect("activate", lambda _i: self.start_scene_analysis())
            item.set_sensitive(not getattr(self, "toc_chapters", None) and bool(self.playlist))
        menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        if not chapters:
            job = getattr(self, "thumb_job", None)
            text = "장면 분석 중..." if job and job.thread.is_alive() else "챕터 정보가 없습니다"
            item = Gtk.MenuItem(label=text)
            item.set_sensitive(False)
            menu.append(item)
        else:
            source = "챕터" if getattr(self, "toc_chapters", None) else "자동 장면 분석"
            head = Gtk.MenuItem(label=f"📑 {source} ({len(chapters)})")
            head.set_sensitive(False)
            menu.append(head)
            current = self.chapter_title_at(self.last_known_pos_ns)
            for pos, title in chapters:
                label = f"{'▶ ' if title == current else '   '}{self.format_time(pos)}  {title}"
                item = Gtk.MenuItem(label=label)
                item.connect("activate", lambda _i, p=pos: (self.seek_direct(p), self.show_osd(f"📑 {self.format_time(p)}")))
                menu.append(item)
        menu.show_all()
        anchor = getattr(self, "progress_scale", None) if not self.is_video_only else getattr(self, "fs_progress_scale", None)
        if anchor is not None and anchor.get_mapped():
            menu.popup_at_widget(anchor, Gdk.Gravity.NORTH, Gdk.Gravity.SOUTH, event)
        else:
            menu.popup_at_pointer(event)
