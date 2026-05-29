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

        简单规则版（生产环境中用 LLM 评判）：
        - 包含 >= 2 个关键词 → correct
        - 包含 1 个关键词 → partial
        - 包含 0 个关键词 → wrong
        """
        if not student_reply.strip():
            return "wrong"

        reply_lower = student_reply.lower()
        matched = sum(1 for kw in step_keywords if kw.lower() in reply_lower)

        if matched >= 2:
            return "correct"
        elif matched >= 1:
            return "partial"
        else:
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
