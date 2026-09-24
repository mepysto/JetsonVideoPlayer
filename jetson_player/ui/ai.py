"""AI 자막 생성 UI: whisper.cpp 작업 시작/취소, 실시간 자막 트랙 갱신, 설정 메뉴"""
import os

from gi.repository import GLib

from ..ai.translate import TranslationJob, make_backend, resolve_backend
from ..ai.whisper import LANGUAGE_NAMES, MODEL_NOTES, AiSubtitleJob, ai_subtitle_path, format_srt, list_whisper_models, whisper_available
from ..settings import settings

AI_COLOR = "#B388FF"
TRANSLATE_TARGETS = [("ko", "한국어"), ("en", "영어"), ("ja", "일본어"), ("zh", "중국어")]
TRANSLATE_BACKENDS = [("auto", "자동 (로컬 우선)"), ("local", "로컬 AI (오프라인)"), ("claude", "Claude API")]
AI_LANGUAGES = [("auto", "자동 감지"), ("ko", "한국어"), ("en", "영어"), ("ja", "일본어"), ("zh", "중국어")]


class AiSubtitlesMixin:
    def start_ai_subtitles(self):
        """현재 영상의 음성을 인식해 AI 자막을 생성합니다 (진행 중이면 취소)."""
        job = getattr(self, "ai_job", None)
        if job and job.is_running():
            self.cancel_ai_subtitles()
            return
        if not self.playlist or not (0 <= self.current_index < len(self.playlist)):
            self.show_osd("재생 중인 영상이 없습니다.")
            return
        path = self.playlist[self.current_index]
        if path.startswith(("http://", "https://")) or not os.path.isfile(path):
            self.show_osd("⚠️ 로컬 영상 파일에서만 AI 자막을 만들 수 있습니다.", duration_sec=3.0)
            return
        model = settings.get("whisper_model")
        if not whisper_available(model):
            self.show_osd("⚠️ AI 자막 엔진이 설치되지 않았습니다: ./scripts/setup_whisper.sh 실행", duration_sec=5.0)
            print("ℹ️ AI 자막을 사용하려면 프로젝트 폴더에서 ./scripts/setup_whisper.sh 를 실행하세요.")
            return
        if self.duration_ns <= 0:
            self.show_osd("영상 길이를 확인하는 중입니다. 잠시 후 다시 시도하세요.")
            return

        translate = settings.get("whisper_translate")
        entry = self.make_subtitle_entry(None, "🤖 AI 자막 (생성 중...)", AI_COLOR, [])
        self.available_subtitles.append(entry)
        ai_index = len(self.available_subtitles) - 1
        # AI 자막만 표시해 기존 자막과 겹치지 않게 합니다 (자막 설정 창에서 함께 켤 수 있음).
        self.active_subtitle_indices = {ai_index}
        self.subtitles_enabled = True
        self.has_subtitles = True
        self.reload_and_apply_subtitles()

        def on_segments(batch):
            if entry is not None:
                entry["events"].extend(batch)
                entry["track"].add_events(batch)

        def on_status(text, fraction):
            self.ai_status = (text, fraction)
            if getattr(self, "ai_job", None) is job_ref[0]:
                self.show_osd(text, duration_sec=1.5)
            self.update_subtitle_button_ui()

        def on_done(srt_path, language, error):
            self.ai_status = None
            if error:
                self.show_osd("⏹ AI 자막 생성을 취소했습니다." if error == "취소됨" else f"❌ AI 자막 실패: {error[:50]}", duration_sec=4.0)
                if not entry["events"] and entry in self.available_subtitles:
                    self.available_subtitles.remove(entry)
                    self.active_subtitle_indices = {0} if self.available_subtitles else set()
                    self.subtitles_enabled = bool(self.available_subtitles)
                    self.reload_and_apply_subtitles()
                return
            lang_name = "영어 번역" if translate else LANGUAGE_NAMES.get(language or "", language or "자동")
            entry["label"] = f"🤖 AI {lang_name} ({os.path.basename(srt_path)})"
            entry["track"].label = entry["label"]
            entry["path"] = srt_path
            self.show_osd(f"🤖 AI 자막 완성: {len(entry['events'])}문장 (다음 재생부터 자동 로드)", duration_sec=4.0)
            self.update_subtitle_button_ui()
            target = settings.get("translate_target")
            if settings.get("whisper_auto_translate") and not translate and language and language != target:
                GLib.timeout_add(1500, lambda: (self.start_translation(entry), False)[1])

        job_ref = [None]
        pos_ms = self.last_known_pos_ns // 1_000_000
        job = AiSubtitleJob(path, self.duration_ns // 1_000_000, start_ms=pos_ms,
                            language=settings.get("whisper_language"), translate=translate, model_name=model,
                            on_segments=on_segments, on_status=on_status, on_done=on_done)
        job_ref[0] = job
        self.ai_job = job
        self.ai_status = ("🤖 AI 자막 준비 중...", 0.0)
        job.start()
        where = f" ({self.format_time(self.last_known_pos_ns)}부터)" if pos_ms >= 30_000 else ""
        self.show_osd(f"🤖 AI 자막 생성을 시작합니다{where} — G: 취소", duration_sec=2.5)

    def cancel_ai_subtitles(self):
        job = getattr(self, "ai_job", None)
        if job and job.is_running():
            job.cancel()

    # ---- 자막 번역 ------------------------------------------------------------
    def _translation_source(self):
        """번역할 자막: 지금 켜져 있는 외부/AI 자막 중 첫 번째 (번역 결과 트랙 제외)"""
        for idx in sorted(self.active_subtitle_indices):
            if 0 <= idx < len(self.available_subtitles):
                entry = self.available_subtitles[idx]
                if entry["events"] and not entry.get("is_translation"):
                    return entry
        return None

    def start_translation(self, source=None):
        """현재 자막 트랙을 설정된 언어(기본 한국어)로 번역합니다 (진행 중이면 취소)."""
        job = getattr(self, "translate_job", None)
        if job and job.is_running():
            self.cancel_translation()
            return
        source = source or self._translation_source()
        if source is None or source not in self.available_subtitles:
            self.show_osd("⚠️ 번역할 자막이 없습니다. 자막을 켜거나 🤖 AI 자막을 먼저 만드세요.", duration_sec=3.5)
            return
        target = settings.get("translate_target")
        backend_name = resolve_backend(settings.get("translate_backend"))
        if backend_name is None:
            self.show_osd("⚠️ 번역 엔진이 없습니다: ./scripts/setup_translator.sh 실행 (또는 Claude API 키 설정)", duration_sec=5.0)
            print("ℹ️ 자막 번역을 쓰려면 ./scripts/setup_translator.sh 를 실행하거나 ANTHROPIC_API_KEY를 설정하세요.")
            return
        if not self.playlist:
            return
        video_path = self.playlist[self.current_index]
        target_name = LANGUAGE_NAMES.get(target, target)
        entry = self.make_subtitle_entry(None, f"🌐 {target_name} 번역 (번역 중...)", "#FFFFFF", [])
        entry["is_translation"] = True
        self.available_subtitles.append(entry)
        self.active_subtitle_indices = {len(self.available_subtitles) - 1}
        self.subtitles_enabled = True
        self.reload_and_apply_subtitles()

        def on_segments(batch):
            entry["events"].extend(batch)
            entry["track"].add_events(batch)

        def on_status(text, fraction):
            self.translate_status = (text, fraction)
            self.show_osd(text, duration_sec=1.5)

        def on_done(events, error):
            self.translate_status = None
            if error and not events:
                self.show_osd("⏹ 번역을 취소했습니다." if error == "취소됨" else f"❌ 번역 실패: {error[:50]}", duration_sec=4.0)
                if entry in self.available_subtitles:
                    self.available_subtitles.remove(entry)
                    self.active_subtitle_indices = {self.available_subtitles.index(source)} if source in self.available_subtitles else set()
                    self.reload_and_apply_subtitles()
                return
            if error:
                self.show_osd(f"⏹ 번역 중단 ({len(events)}문장까지 표시)", duration_sec=3.0)
                return
            path = ai_subtitle_path(video_path, target)
            with open(path, "w", encoding="utf-8") as f:
                f.write(format_srt(events))
            entry["label"] = f"🌐 {target_name} 번역 ({os.path.basename(path)})"
            entry["track"].label = entry["label"]
            entry["path"] = path
            print(f"🌐 [자막 번역] {len(events)}문장 → {path}")
            self.show_osd(f"🌐 {target_name} 번역 완성: {len(events)}문장 (다음 재생부터 자동 로드)", duration_sec=4.0)
            self.update_subtitle_button_ui()

        job = TranslationJob(list(source["events"]), target, make_backend(backend_name),
                             position_ms=self.last_known_pos_ns // 1_000_000,
                             on_segments=on_segments, on_status=on_status, on_done=on_done)
        self.translate_job = job
        self.translate_status = ("🌐 번역 준비 중...", 0.0)
        job.start()
        engine = "로컬 AI" if backend_name == "local" else "Claude API"
        self.show_osd(f"🌐 {target_name} 번역 시작 ({engine}) — Shift+G: 취소", duration_sec=2.5)

    def cancel_translation(self):
        job = getattr(self, "translate_job", None)
        if job and job.is_running():
            job.cancel()

    def translation_menu_label(self):
        job = getattr(self, "translate_job", None)
        if job and job.is_running():
            status = getattr(self, "translate_status", None)
            pct = f" {status[1] * 100:.0f}%" if status else ""
            return f"⏹ 자막 번역 취소{pct} (Shift+G)"
        return f"🌐 자막을 {LANGUAGE_NAMES.get(settings.get('translate_target'), '한국어')}로 번역 (Shift+G)"

    # ---- YouTube 영상 자동 AI 자막 ------------------------------------------------
    def mark_for_auto_ai_subtitles(self, path):
        """설정이 켜져 있으면 이 영상이 재생될 때 AI 자막을 자동으로 만듭니다."""
        if settings.get("youtube_auto_ai_subtitles"):
            self.auto_ai_paths.add(path)

    def maybe_start_auto_ai_subtitles(self):
        """[영상 길이가 처음 확인될 때 호출] 자동 생성 대상이면 AI 자막을 시작합니다."""
        if not self.playlist or not (0 <= self.current_index < len(self.playlist)):
            return
        path = self.playlist[self.current_index]
        if path not in self.auto_ai_paths:
            return
        self.auto_ai_paths.discard(path)
        if self.available_subtitles:
            return  # 자막이 이미 있음 (이전에 만든 AI 자막 포함)
        job = getattr(self, "ai_job", None)
        if job and job.is_running():
            return
        if whisper_available(settings.get("whisper_model")):
            print(f"🤖 [자동 AI 자막] {os.path.basename(path)}")
            self.start_ai_subtitles()

    def ai_menu_label(self):
        job = getattr(self, "ai_job", None)
        if job and job.is_running():
            status = getattr(self, "ai_status", None)
            pct = f" {status[1] * 100:.0f}%" if status else ""
            return f"⏹ AI 자막 생성 취소{pct} (G)"
        return "🤖 AI 자막 생성 (G)"

    def ai_setting_entries(self):
        """⋯ 메뉴용: AI 인식 언어 선택, 영어 번역"""
        current = settings.get("whisper_language")
        languages = [(label, (lambda code=code: settings.set("whisper_language", code)), code == current)
                     for code, label in AI_LANGUAGES]
        entries = [("submenu", "🤖 AI 자막 언어", languages)]
        models = list_whisper_models()
        if len(models) > 1:
            current_model = settings.get("whisper_model")
            if current_model not in models:
                current_model = models[0]
            entries.append(("submenu", "🤖 AI 인식 모델", [
                (f"{m}  —  {MODEL_NOTES.get(m, '')}".rstrip(" —"), (lambda m=m: self._set_whisper_model(m)), m == current_model)
                for m in models]))
        return entries + [
            ("check", "🤖 AI 자막을 영어로 번역", settings.get("whisper_translate"),
             lambda: settings.set("whisper_translate", not settings.get("whisper_translate"))),
            ("check", "🤖 YouTube 영상은 AI 자막 자동 생성", settings.get("youtube_auto_ai_subtitles"),
             lambda: settings.set("youtube_auto_ai_subtitles", not settings.get("youtube_auto_ai_subtitles"))),
            ("submenu", "🌐 번역 언어", [(label, (lambda c=code: settings.set("translate_target", c)), code == settings.get("translate_target"))
                                        for code, label in TRANSLATE_TARGETS]),
            ("submenu", "🌐 번역 엔진", [(label, (lambda c=code: settings.set("translate_backend", c)), code == settings.get("translate_backend"))
                                        for code, label in TRANSLATE_BACKENDS]),
            ("check", "🌐 AI 자막을 만들면 자동으로 번역", settings.get("whisper_auto_translate"),
             lambda: settings.set("whisper_auto_translate", not settings.get("whisper_auto_translate"))),
        ]

    def _set_whisper_model(self, name):
        settings.set("whisper_model", name)
        self.show_osd(f"🤖 AI 인식 모델: {name} (다음 생성부터 적용)")
