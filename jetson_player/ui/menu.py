"""상단바 ⋯ 더 보기 메뉴: 자주 쓰지 않는 기능과 부가 기능을 한곳에 모읍니다."""
from gi.repository import Gdk, Gtk


class MenuMixin:
    def show_more_menu(self, button):
        """⋯ 버튼 아래에 기능 메뉴를 띄웁니다. 항목은 열 때마다 현재 상태로 새로 구성합니다."""
        menu = Gtk.Menu()
        anchor = button

        def add(label, callback, sensitive=True):
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(sensitive)
            item.connect("activate", lambda _i: callback())
            menu.append(item)
            return item

        def add_check(label, active, callback):
            item = Gtk.CheckMenuItem(label=label)
            item.set_active(active)
            item.connect("toggled", lambda _i: callback())
            menu.append(item)
            return item

        def add_submenu(label, entries):
            """entries: [(라벨, 콜백, 선택됨 여부), ...]"""
            parent = Gtk.MenuItem(label=label)
            sub = Gtk.Menu()
            group = None
            for text, callback, selected in entries:
                item = Gtk.RadioMenuItem.new_with_label_from_widget(group, text)
                group = item
                item.set_active(selected)
                item.connect("toggled", lambda i, cb=callback: cb() if i.get_active() else None)
                sub.append(item)
            parent.set_submenu(sub)
            menu.append(parent)
            return parent

        has_video = bool(self.playlist) and self.pipeline is not None

        # 1) 현재 영상
        add("🔖 북마크 목록 (Ctrl+B)", lambda: self.show_bookmarks_popover(anchor), has_video)
        add("➕ 현재 위치 북마크 (B)", self.add_bookmark, has_video)
        add("📸 스크린샷 캡처 (Ctrl+S)", self.capture_screenshot, has_video)
        for label, callback in self.more_menu_video_items():
            add(label, callback, has_video)
        menu.append(Gtk.SeparatorMenuItem())

        # 2) 재생 / 화면 설정 (Phase 4 기능이 채움)
        for kind, *args in self.more_menu_setting_items():
            if kind == "check":
                add_check(*args)
            elif kind == "submenu":
                add_submenu(*args)
            else:
                add(*args)
        menu.append(Gtk.SeparatorMenuItem())

        # 3) 도구 / 정보
        add("📱 스마트폰 웹 리모컨...", lambda: self.show_remote_popover(anchor))
        add_check("ℹ️ 미디어 정보 HUD (I)", self.is_hud_visible, self.toggle_hud)
        add_check("📌 항상 위에 표시 (T)", self.is_keep_above, self.toggle_keep_above)
        add("❓ 단축키 안내 (F1)", self.show_help_dialog)

        menu.show_all()
        menu.popup_at_widget(button, Gdk.Gravity.SOUTH_EAST, Gdk.Gravity.NORTH_EAST, None)

    def more_menu_video_items(self):
        """현재 영상 관련 추가 항목 [(라벨, 콜백), ...]"""
        return [
            (self.ai_menu_label(), self.start_ai_subtitles),
            ("📑 챕터 / 장면 목록 (K)", self.show_chapters_menu),
        ]

    def more_menu_setting_items(self):
        """재생/화면 설정 항목 [("item"|"check"|"submenu", ...)]"""
        return list(self.viewing_setting_entries()) + list(self.ai_setting_entries())
