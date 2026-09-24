"""AI 자막 생성 UI: whisper.cpp 작업 시작/취소, 실시간 자막 트랙 갱신, 설정 메뉴"""
import os

from ..ai.whisper import LANGUAGE_NAMES, AiSubtitleJob, whisper_available
from ..settings import settings

AI_COLOR = "#B388FF"
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
        return [
            ("submenu", "🤖 AI 자막 언어", languages),
            ("check", "🤖 AI 자막을 영어로 번역", settings.get("whisper_translate"),
             lambda: settings.set("whisper_translate", not settings.get("whisper_translate"))),
        ]
