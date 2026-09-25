"""사이드바 재생목록 트리 패널"""
import logging
import os

from gi.repository import GLib, Gdk, Gtk, Pango

from ..library import sort_video_paths
from ..settings import settings
from ..storage import resume_cache
from ..system import open_file_location
from ..youtube import youtube_mgr

log = logging.getLogger(__name__)


class PlaylistPanelMixin:
    def build_playlist_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.get_style_context().add_class("sidebar")
        panel.set_size_request(240, -1)
        panel.set_border_width(12)

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="재생목록", xalign=0)
        title.get_style_context().add_class("section-title")
        self.playlist_count_label = Gtk.Label(label=f"{len(self.playlist)}개", xalign=1)
        self.playlist_count_label.get_style_context().add_class("muted")
        self.sort_button = Gtk.Button(label="↕ 이름순")
        self.sort_button.get_style_context().add_class("tree-tool-btn")
        self.sort_button.set_tooltip_text("재생목록 정렬 기준 변경 (이름 → 최근 수정 → 크기)")
        self.sort_button.connect("clicked", self.cycle_playlist_sort)
        heading.pack_start(title, True, True, 0)
        heading.pack_end(self.sort_button, False, False, 0)
        heading.pack_end(self.playlist_count_label, False, False, 0)
        panel.pack_start(heading, False, False, 2)

        # 검색창
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("영상 검색...")
        self.search_entry.connect("search-changed", self.on_search_changed)
        self.search_entry.connect("activate", self.on_search_activate)
        # Esc: 검색어를 지우고 포커스를 해제 (단축키 다시 활성화)
        self.search_entry.connect("stop-search", lambda e: (e.set_text(""), self.set_focus(None)))
        panel.pack_start(self.search_entry, False, False, 2)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if not self.is_single_file_mode:
            exp_btn = Gtk.Button(label="전체 펼치기")
            exp_btn.get_style_context().add_class("tree-tool-btn")
            exp_btn.set_tooltip_text("모든 폴더 펼치기")
            exp_btn.connect("clicked", lambda _b: self.playlist_treeview.expand_all())
            col_btn = Gtk.Button(label="전체 접기")
            col_btn.get_style_context().add_class("tree-tool-btn")
            col_btn.set_tooltip_text("모든 폴더 접기")
            col_btn.connect("clicked", lambda _b: self.collapse_playlist_tree())
            tools.pack_start(exp_btn, True, True, 0)
            tools.pack_start(col_btn, True, True, 0)

        self.wrap_button = Gtk.Button(label="줄바꿈")
        self.wrap_button.get_style_context().add_class("tree-tool-btn")
        self.wrap_button.set_tooltip_text("긴 파일명 자동 줄바꿈 켜기/끄기")
        self.wrap_button.connect("clicked", self.on_wrap_toggle)

        open_loc_btn = Gtk.Button(label="📂 위치")
        open_loc_btn.get_style_context().add_class("tree-tool-btn")
        open_loc_btn.set_tooltip_text("선택 또는 현재 재생 중인 영상의 폴더 위치를 파일 브라우저로 열기")
        open_loc_btn.connect("clicked", lambda _b: self.open_selected_or_current_location())

        if self.is_single_file_mode:
            tools.pack_start(self.wrap_button, True, True, 0)
            tools.pack_start(open_loc_btn, True, True, 0)
        else:
            tools.pack_start(self.wrap_button, False, False, 0)
            tools.pack_start(open_loc_btn, False, False, 0)
        panel.pack_start(tools, False, False, 2)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.tree_store = Gtk.TreeStore(str, str, str, int, bool)
        self.playlist_treeview = Gtk.TreeView(model=self.tree_store)
        self.playlist_treeview.set_headers_visible(False)
        self.playlist_treeview.set_activate_on_single_click(True)
        self.playlist_treeview.set_has_tooltip(True)
        self.playlist_treeview.connect("query-tooltip", self.on_tree_query_tooltip)
        self.playlist_treeview.connect("size-allocate", self.on_tree_size_allocate)
        self.playlist_treeview.connect("row-activated", self.on_tree_row_activated)
        self.playlist_treeview.connect("row-expanded", self.on_tree_row_expanded)
        self.playlist_treeview.connect("row-collapsed", self.on_tree_row_collapsed)
        self.playlist_treeview.connect("button-press-event", self.on_tree_button_press)

        col = Gtk.TreeViewColumn("Track")
        r_icon = Gtk.CellRendererText()
        r_icon.set_property("xpad", 4)
        col.pack_start(r_icon, False)
        col.add_attribute(r_icon, "text", 0)

        self.r_text = Gtk.CellRendererText()
        self.r_text.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.r_text.set_property("ypad", 6)
        col.pack_start(self.r_text, True)
        col.add_attribute(self.r_text, "markup", 1)
        self.playlist_treeview.append_column(col)

        self.populate_playlist_tree()

        scroll.add(self.playlist_treeview)
        panel.pack_start(scroll, True, True, 0)
        return panel

    def open_selected_or_current_location(self, target_path=None):
        """선택된 재생목록 항목 또는 현재 재생 중인 영상의 폴더 위치를 파일 브라우저로 엽니다."""
        path_to_open = target_path
        if not path_to_open and self.playlist_treeview:
            sel = self.playlist_treeview.get_selection()
            model, tree_iter = sel.get_selected()
            if tree_iter:
                path_to_open = model.get_value(tree_iter, 2)

        if not path_to_open and self.playlist and 0 <= self.current_index < len(self.playlist):
            path_to_open = self.playlist[self.current_index]

        if not path_to_open:
            yt_dir = os.path.expanduser("~/Videos/YouTube")
            if os.path.exists(yt_dir):
                path_to_open = yt_dir
            else:
                self.show_osd("⚠️ 열 위치가 지정되지 않았습니다.")
                return

        success = open_file_location(path_to_open)
        if success:
            dir_name = path_to_open if os.path.isdir(path_to_open) else os.path.dirname(path_to_open)
            self.show_osd(f"📂 폴더 열기: {os.path.basename(dir_name) or dir_name}", duration_sec=2.0)
            log.info(f"📂 [파일 위치 열기] {path_to_open}")
        else:
            self.show_osd("⚠️ 파일 브라우저를 열지 못했습니다.")

    def open_selected_or_current_location_by_index(self, idx=None):
        target = None
        if idx is not None and 0 <= idx < len(self.playlist):
            target = self.playlist[idx]
        self.open_selected_or_current_location(target)

    def on_tree_button_press(self, treeview, event):
        """재생목록 항목 우클릭 시 컨텍스트 메뉴(파일 위치 열기, 재생, 경로 복사 등)를 표시합니다."""
        if event.button == 3:  # 마우스 우클릭
            path_info = treeview.get_path_at_pos(int(event.x), int(event.y))
            if path_info:
                tree_path, _col, _cell_x, _cell_y = path_info
                tree_iter = self.tree_store.get_iter(tree_path)
                file_path = self.tree_store.get_value(tree_iter, 2)
                item_idx = self.tree_store.get_value(tree_iter, 3)
                is_dir = self.tree_store.get_value(tree_iter, 4)

                menu = Gtk.Menu()

                # 1. 파일 위치 열기
                loc_item = Gtk.MenuItem(label="📂 파일 위치 열기 (파일 브라우저)")
                loc_item.connect("activate", lambda _m: self.open_selected_or_current_location(file_path))
                menu.append(loc_item)

                if not is_dir and item_idx >= 0:
                    # 2. 지금 재생
                    play_item = Gtk.MenuItem(label="▶️ 지금 재생")
                    play_item.connect("activate", lambda _m: self.play_index_direct(item_idx))
                    menu.append(play_item)

                    if file_path in self.play_queue:
                        q_item = Gtk.MenuItem(label="✕ 대기열에서 제거")
                        q_item.connect("activate", lambda _m: self.unqueue(file_path))
                    else:
                        q_item = Gtk.MenuItem(label="⏭ 다음에 재생 (대기열 추가)")
                        q_item.connect("activate", lambda _m: self.queue_next(file_path))
                    menu.append(q_item)

                menu.append(Gtk.SeparatorMenuItem())

                refresh_item = Gtk.MenuItem(label="🔄 재생목록 새로고침 (F5)")
                refresh_item.connect("activate", lambda _m: self.rescan_playlist())
                menu.append(refresh_item)

                # 3. 전체 경로 복사
                copy_path_item = Gtk.MenuItem(label="📋 전체 경로 복사")
                def on_copy_path(_m):
                    cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                    cb.set_text(file_path, -1)
                    self.show_osd("📋 파일 경로가 복사되었습니다!", duration_sec=1.5)
                copy_path_item.connect("activate", on_copy_path)
                menu.append(copy_path_item)

                # 4. 파일 이름 복사
                copy_name_item = Gtk.MenuItem(label="📋 파일 이름 복사")
                def on_copy_name(_m):
                    cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                    cb.set_text(os.path.basename(file_path), -1)
                    self.show_osd("📋 파일 이름이 복사되었습니다!", duration_sec=1.5)
                copy_name_item.connect("activate", on_copy_name)
                menu.append(copy_name_item)

                menu.show_all()
                menu.popup_at_pointer(event)
                return True
        return False

    def on_search_changed(self, entry):
        self.search_text = entry.get_text().strip().lower()
        self.populate_playlist_tree()

    def on_search_activate(self, _entry):
        """검색창에서 Enter: 첫 번째 검색 결과를 재생하고 포커스를 해제해 단축키를 다시 사용할 수 있게 합니다."""
        if self.playlist_tree_iters:
            first_idx = min(self.playlist_tree_iters.keys())
            if first_idx != self.current_index:
                self.play_index_direct(first_idx)
        self.set_focus(None)

    def on_paned_notify_position(self, paned, _gparam):
        """사용자가 스플리터 핸들을 드래그할 때 사이드바 너비를 기억합니다."""
        if self.is_adjusting_paned or not self.sidebar or not self.sidebar.get_visible():
            return
        pos = paned.get_position()
        alloc_w = paned.get_allocation().width
        if alloc_w > 0 and pos > 0:
            current_s_w = alloc_w - pos
            if current_s_w >= 200:
                self.sidebar_width = current_s_w

    def on_paned_size_allocate(self, paned, allocation):
        """창 크기 조절 시 사이드바의 설정된 너비를 정확히 유지합니다."""
        if not self.sidebar or not self.sidebar.get_visible():
            return
        target_pos = max(200, allocation.width - self.sidebar_width)
        if abs(paned.get_position() - target_pos) > 2:
            self.is_adjusting_paned = True
            paned.set_position(target_pos)
            self.is_adjusting_paned = False

    def on_wrap_toggle(self, _button):
        """재생목록 내 긴 파일명의 자동 줄바꿈을 토글합니다."""
        self.is_wrap_enabled = not self.is_wrap_enabled
        if not self.r_text:
            return
        if self.is_wrap_enabled:
            if self.wrap_button:
                self.wrap_button.get_style_context().add_class("active")
            self.r_text.set_property("wrap-mode", Pango.WrapMode.WORD_CHAR)
            self.r_text.set_property("ellipsize", Pango.EllipsizeMode.NONE)
            self.update_tree_wrap_width()
        else:
            if self.wrap_button:
                self.wrap_button.get_style_context().remove_class("active")
            self.r_text.set_property("ellipsize", Pango.EllipsizeMode.END)
            self.r_text.set_property("wrap-width", -1)
        if self.playlist_treeview:
            self.playlist_treeview.queue_resize()

    def update_tree_wrap_width(self):
        """트리뷰 너비에 맞춰 셀 렌더러의 wrap-width를 자동 계산합니다."""
        if not self.is_wrap_enabled or not self.playlist_treeview or not self.r_text:
            return
        alloc = self.playlist_treeview.get_allocation()
        if alloc.width > 50:
            target_w = max(120, alloc.width - 65)
            if self.r_text.get_property("wrap-width") != target_w:
                self.r_text.set_property("wrap-width", target_w)

    def on_tree_size_allocate(self, _widget, allocation):
        """트리뷰 크기 변경 시 줄바꿈 너비를 실시간 동기화합니다."""
        if self.is_wrap_enabled and self.r_text:
            target_w = max(120, allocation.width - 65)
            if self.r_text.get_property("wrap-width") != target_w:
                self.r_text.set_property("wrap-width", target_w)

    def on_tree_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        """재생목록 항목에 마우스 호버 시 전체 파일명 및 경로를 툴팁으로 표시합니다."""
        res = widget.get_tooltip_context(x, y, keyboard_mode)
        if not res:
            return False
        bool_val, bx, by, model, path, tree_iter = res
        if not bool_val or tree_iter is None:
            return False

        try:
            is_dir = model.get_value(tree_iter, 4)
            full_path = model.get_value(tree_iter, 2)
            idx = model.get_value(tree_iter, 3)

            if is_dir:
                dir_name = os.path.basename(full_path)
                safe_name = GLib.markup_escape_text(dir_name)
                safe_path = GLib.markup_escape_text(full_path)
                tooltip.set_markup(
                    f"📁 <b>{safe_name}</b>\n"
                    f"<span color='#8f98a8' size='smaller'>{safe_path}</span>"
                )
            else:
                file_name = os.path.basename(full_path)
                safe_name = GLib.markup_escape_text(file_name)
                safe_path = GLib.markup_escape_text(full_path)
                num_badge = f"<span color='#e9ff5b' weight='bold'>#{idx + 1}</span> " if idx >= 0 else ""
                tooltip.set_markup(
                    f"🎬 {num_badge}<b>{safe_name}</b>\n"
                    f"<span color='#8f98a8' size='smaller'>{safe_path}</span>"
                )
            widget.set_tooltip_row(tooltip, path)
            return True
        except Exception:
            return False

    def on_playlist_toggle(self, _button):
        is_vis = not self.sidebar.get_visible()
        self.sidebar.set_visible(is_vis)
        if is_vis and self.main_paned:
            alloc_w = self.main_paned.get_allocation().width
            if alloc_w > 0:
                self.main_paned.set_position(max(200, alloc_w - self.sidebar_width))

    def _video_row_style(self, idx, path):
        """재생목록 영상 행의 아이콘과 Pango 마크업: 재생 중(▶), 시청 완료(✓), 진행률, 대기열 순번, 삭제된 파일"""
        safe_name = GLib.markup_escape_text(os.path.basename(path))
        is_active = idx == self.current_index
        suffix = ""
        queue = getattr(self, "play_queue", [])
        if path in queue:
            suffix += f"  <span color='#111318' background='#e9ff5b' size='smaller' weight='bold'> 다음 {queue.index(path) + 1} </span>"
        if not os.path.exists(path):
            return "⚠", f"<span color='#5b6474' strikethrough='true'>{safe_name}</span>{suffix}"
        ratio, watched = resume_cache.get_progress(path)
        if ratio is not None and not is_active:
            filled = max(1, min(5, int(round(ratio * 5))))
            bar = "▰" * filled + "▱" * (5 - filled)
            suffix = f"  <span color='#70798a' size='smaller'>{bar} {int(ratio * 100)}%</span>" + suffix
        if is_active:
            return "▶", f"<span color='#e9ff5b' weight='bold'>{safe_name}</span>{suffix}"
        if watched and ratio is None:
            return "✓", f"<span color='#8f98a8'>{safe_name}</span>{suffix}"
        return "🎬", f"<span color='#dce2ec'>{safe_name}</span>{suffix}"

    # ---- 정렬 / 대기열 -------------------------------------------------
    SORT_LABELS = {"name": "이름순", "mtime": "최근 수정순", "size": "크기순"}

    def cycle_playlist_sort(self, _button=None):
        order = ["name", "mtime", "size"]
        cur = settings.get("playlist_sort")
        mode = order[(order.index(cur) + 1) % len(order)] if cur in order else "name"
        settings.set("playlist_sort", mode)
        self.apply_playlist_sort()
        self.show_osd(f"↕ 재생목록 정렬: {self.SORT_LABELS[mode]}")

    def apply_playlist_sort(self):
        """현재 재생 중인 영상을 유지한 채 재생목록을 설정된 기준으로 다시 정렬합니다."""
        mode = settings.get("playlist_sort")
        if getattr(self, "sort_button", None):
            self.sort_button.set_label(f"↕ {self.SORT_LABELS.get(mode, '이름순')}")
        if not self.playlist:
            return
        current = self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None
        self.playlist = sort_video_paths(self.playlist, mode)
        if current in self.playlist:
            self.current_index = self.playlist.index(current)
        self.populate_playlist_tree()
        self.refresh_playlist_ui()

    def queue_next(self, path):
        """영상을 "다음에 재생" 대기열 끝에 추가합니다 (이미 있으면 무시)."""
        if path not in self.play_queue:
            self.play_queue.append(path)
            self.show_osd(f"⏭ 다음에 재생 ({len(self.play_queue)}번째): {os.path.basename(path)[:30]}")
            self.refresh_playlist_ui()

    def unqueue(self, path):
        if path in self.play_queue:
            self.play_queue.remove(path)
            self.show_osd("대기열에서 제거했습니다.")
            self.refresh_playlist_ui()

    def pop_queued_index(self):
        """대기열에서 재생목록에 남아 있는 첫 영상의 인덱스를 꺼냅니다."""
        while self.play_queue:
            path = self.play_queue.pop(0)
            if path in self.playlist:
                return self.playlist.index(path)
        return None

    def _video_row(self, idx, path):
        icon, markup = self._video_row_style(idx, path)
        return [icon, markup, path, idx, False]

    def populate_playlist_tree(self):
        """재생목록을 디렉토리 계층 구조의 트리로 구축합니다 (검색 필터 및 유튜브 가상 폴더 지원)."""
        if not self.tree_store:
            return
        self.tree_store.clear()
        self.playlist_tree_iters.clear()
        if getattr(self, "playlist_count_label", None):
            self.playlist_count_label.set_text(f"{len(self.playlist)}개")

        if not self.playlist:
            return

        abs_root = os.path.abspath(self.input_path) if (self.input_path and os.path.isdir(self.input_path)) else None

        filtered_items = []
        for idx, p in enumerate(self.playlist):
            fname = os.path.basename(p)
            if self.search_text and (self.search_text not in fname.lower() and self.search_text not in p.lower()):
                continue
            filtered_items.append((idx, p))

        if not abs_root:
            for idx, p in filtered_items:
                v_iter = self.tree_store.append(
                    None,
                    self._video_row(idx, p)
                )
                self.playlist_tree_iters[idx] = v_iter
            return

        def is_subpath(child, parent):
            try:
                rel = os.path.relpath(child, parent)
                return not rel.startswith("..") and not os.path.isabs(rel)
            except ValueError:
                return False

        # 내부 파일과 외부(유튜브 등) 파일 분리
        internal_items = []
        external_yt_items = []
        external_other_items = []
        yt_dir = os.path.abspath(youtube_mgr.download_dir)

        for item in filtered_items:
            idx, p = item
            if is_subpath(p, abs_root):
                internal_items.append(item)
            elif is_subpath(p, yt_dir):
                external_yt_items.append(item)
            else:
                external_other_items.append(item)

        # 1. 내부 디렉토리별 하위 영상 파일 수 카운트
        dir_counts = {}
        for idx, p in internal_items:
            rel_p = os.path.relpath(p, abs_root)
            parts = rel_p.split(os.sep)[:-1]
            for i in range(1, len(parts) + 1):
                d = os.sep.join(parts[:i])
                dir_counts[d] = dir_counts.get(d, 0) + 1

        # 2. 계층형 폴더 및 비디오 노드 추가
        dir_iters = {}
        for idx, p in internal_items:
            rel_p = os.path.relpath(p, abs_root)
            parts = rel_p.split(os.sep)
            fname = parts[-1]
            dir_parts = parts[:-1]

            cur_p = ""
            parent_iter = None
            for d in dir_parts:
                cur_p = os.path.join(cur_p, d) if cur_p else d
                if cur_p not in dir_iters:
                    cnt = dir_counts.get(cur_p, 0)
                    safe_d = GLib.markup_escape_text(d)
                    lbl = f"<b>{safe_d}</b> <span color='#70798a' size='smaller'>({cnt})</span>"
                    d_iter = self.tree_store.append(
                        parent_iter,
                        ["📁", lbl, cur_p, -1, True]
                    )
                    dir_iters[cur_p] = d_iter
                    parent_iter = d_iter
                else:
                    parent_iter = dir_iters[cur_p]

            v_iter = self.tree_store.append(
                parent_iter,
                self._video_row(idx, p)
            )
            self.playlist_tree_iters[idx] = v_iter

        # 3. 외부 유튜브 영상 전용 가상 폴더 추가
        if external_yt_items:
            yt_root_lbl = f"<b>📺 YouTube 영상</b> <span color='#70798a' size='smaller'>({len(external_yt_items)})</span>"
            yt_parent = self.tree_store.append(
                None,
                ["📁", yt_root_lbl, yt_dir, -1, True]
            )
            for idx, p in external_yt_items:
                v_iter = self.tree_store.append(
                    yt_parent,
                    self._video_row(idx, p)
                )
                self.playlist_tree_iters[idx] = v_iter

        # 4. 기타 외부 파일 전용 가상 폴더 추가
        if external_other_items:
            ext_root_lbl = f"<b>💾 외부 파일</b> <span color='#70798a' size='smaller'>({len(external_other_items)})</span>"
            ext_parent = self.tree_store.append(
                None,
                ["📁", ext_root_lbl, "", -1, True]
            )
            for idx, p in external_other_items:
                v_iter = self.tree_store.append(
                    ext_parent,
                    self._video_row(idx, p)
                )
                self.playlist_tree_iters[idx] = v_iter

        if self.search_text and self.playlist_treeview:
            self.playlist_treeview.expand_all()

    def on_tree_row_activated(self, treeview, path, _column):
        """트리 항목 클릭 시: 폴더는 펼치기/접기 토글, 비디오 파일은 즉시 재생"""
        model = treeview.get_model()
        tree_iter = model.get_iter(path)
        is_dir = model.get_value(tree_iter, 4)
        if is_dir:
            if treeview.row_expanded(path):
                treeview.collapse_row(path)
            else:
                treeview.expand_row(path, False)
        else:
            idx = model.get_value(tree_iter, 3)
            if idx != self.current_index and 0 <= idx < len(self.playlist):
                self.current_index = idx
                self.play_current_video()

    def on_tree_row_expanded(self, _treeview, tree_iter, _path):
        if self.tree_store and self.tree_store.get_value(tree_iter, 4):
            self.tree_store.set_value(tree_iter, 0, "📂")

    def on_tree_row_collapsed(self, _treeview, tree_iter, _path):
        if self.tree_store and self.tree_store.get_value(tree_iter, 4):
            self.tree_store.set_value(tree_iter, 0, "📁")

    def collapse_playlist_tree(self):
        """전체 폴더를 접되, 현재 재생 중인 영상의 폴더는 열어둡니다."""
        if self.playlist_treeview:
            self.playlist_treeview.collapse_all()
            if 0 <= self.current_index < len(self.playlist):
                cur_iter = self.playlist_tree_iters.get(self.current_index)
                if cur_iter and self.tree_store.iter_is_valid(cur_iter):
                    path = self.tree_store.get_path(cur_iter)
                    self.playlist_treeview.expand_to_path(path)
                    self.playlist_treeview.scroll_to_cell(path, None, True, 0.5, 0.0)

    def refresh_playlist_ui(self):
        if not self.playlist:
            return
        current_path = self.playlist[self.current_index]
        abs_root = os.path.abspath(self.input_path) if (self.input_path and os.path.isdir(self.input_path)) else None
        
        def is_subpath(child, parent):
            try:
                rel = os.path.relpath(child, parent)
                return not rel.startswith("..") and not os.path.isabs(rel)
            except ValueError:
                return False

        if abs_root and is_subpath(current_path, abs_root):
            display_name = os.path.relpath(current_path, abs_root)
        else:
            display_name = os.path.basename(current_path)

        self.now_playing_label.set_text(
            f"재생 중  ·  {display_name}   {self.current_index + 1}/{len(self.playlist)}"
        )
        self.now_playing_label.set_tooltip_text(f"{display_name}\n({current_path})")

        if not self.tree_store or not self.playlist_tree_iters:
            return

        active_iter = None
        for idx, tree_iter in self.playlist_tree_iters.items():
            if not self.tree_store.iter_is_valid(tree_iter):
                continue
            path_val = self.tree_store.get_value(tree_iter, 2)
            icon, markup = self._video_row_style(idx, path_val)
            self.tree_store.set_value(tree_iter, 0, icon)
            self.tree_store.set_value(tree_iter, 1, markup)
            if idx == self.current_index:
                active_iter = tree_iter

        if active_iter and self.playlist_treeview:
            tree_path = self.tree_store.get_path(active_iter)
            if tree_path:
                self.playlist_treeview.expand_to_path(tree_path)
                sel = self.playlist_treeview.get_selection()
                sel.select_iter(active_iter)
                GLib.idle_add(lambda: self.playlist_treeview.scroll_to_cell(tree_path, None, True, 0.5, 0.0))

    def update_playlist_item_ui(self, idx, new_path):
        """재생목록 항목 경로가 변경(H.265 변환 등)되었을 때 트리뷰 UI를 동기화합니다."""
        if not self.tree_store or idx not in self.playlist_tree_iters:
            return
        tree_iter = self.playlist_tree_iters[idx]
        if self.tree_store.iter_is_valid(tree_iter):
            icon, markup = self._video_row_style(idx, new_path)
            self.tree_store.set_value(tree_iter, 0, icon)
            self.tree_store.set_value(tree_iter, 1, markup)
            self.tree_store.set_value(tree_iter, 2, new_path)
