"""PhotoTutorAgent -- 管理拍照→引导→解答的完整会话生命周期。"""

import logging

from .base_agent import BaseAgent
from core.event_bus import Event, EventType
from core.photo_session import PhotoSessionManager

logger = logging.getLogger(__name__)


class PhotoTutorAgent(BaseAgent):
    """第6个Agent：拍照引导教学。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_manager = PhotoSessionManager()

    @property
    def subscribed_events(self) -> list[EventType]:
        return [
            EventType.PHOTO_SESSION_STARTED,
            EventType.PROBLEM_RECOGNIZED,
            EventType.GUIDANCE_QUESTION,
            EventType.STUDENT_PHOTO_REPLY,
            EventType.REPLY_JUDGED,
            EventType.STEP_COMPLETED,
            EventType.SOLUTION_REVEALED,
            EventType.PHOTO_SESSION_ENDED,
        ]

    async def handle_event(self, event: Event) -> None:
        event_map = {
            EventType.PHOTO_SESSION_STARTED: self._on_session_started,
            EventType.PROBLEM_RECOGNIZED: self._on_problem_recognized,
            EventType.GUIDANCE_QUESTION: self._on_guidance_question,
            EventType.STUDENT_PHOTO_REPLY: self._on_student_reply,
            EventType.REPLY_JUDGED: self._on_reply_judged,
            EventType.STEP_COMPLETED: self._on_step_completed,
            EventType.SOLUTION_REVEALED: self._on_solution_revealed,
            EventType.PHOTO_SESSION_ENDED: self._on_session_ended,
        }
        handler = event_map.get(event.type)
        if handler:
            await handler(event)

    def _judge_reply(self, student_reply: str, step_keywords: set[str]) -> str:
        """
        评判学生回复质量。

        LLM 评判（带降级）：
        - 用 LLM 理解回复是否基本正确
        - LLM 不可用时降级到关键词匹配
        """
        if not student_reply.strip():
            return "wrong"

        try:
            from openai import OpenAI
            from config.settings import settings

            if settings.openai_api_key:
                client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
                resp = client.chat.completions.create(
                    model=settings.openai_model,
                    messages=[{
                        "role": "system",
                        "content": "你是数学老师。判断学生对当前步骤的回答是否正确、部分正确还是错误。只输出一个词: correct, partial, wrong。partial表示思路对但不够完整或不够具体。"
                    }, {
                        "role": "user",
                        "content": f"当前步骤关键思路：{step_keywords}\n学生回答：{student_reply}\n\n评判（correct/partial/wrong）："
                    }],
                    max_tokens=5, temperature=0, timeout=8.0,
                )
                raw = resp.choices[0].message.content.strip().lower()
                if "correct" in raw:
                    return "correct"
                elif "partial" in raw:
                    return "partial"
                return "wrong"
        except Exception:
            pass

        # LLM 不可用时降级到关键词匹配
        reply_lower = student_reply.lower()
        matched = sum(1 for kw in step_keywords if kw.lower() in reply_lower)
        if matched >= 2:
            return "correct"
        elif matched >= 1:
            return "partial"
        return "wrong"

    async def _on_session_started(self, event: Event) -> None:
        logger.info("[PhotoTutor] Session started for learner=%s", event.learner_id)

    async def _on_problem_recognized(self, event: Event) -> None:
        pass

    async def _on_guidance_question(self, event: Event) -> None:
        pass

    async def _on_student_reply(self, event: Event) -> None:
        pass

    async def _on_reply_judged(self, event: Event) -> None:
        pass

    async def _on_step_completed(self, event: Event) -> None:
        pass

    async def _on_solution_revealed(self, event: Event) -> None:
        pass

    async def _on_session_ended(self, event: Event) -> None:
        pass
