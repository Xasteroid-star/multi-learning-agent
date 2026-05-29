"""拍照会话模型 -- 管理一次拍照→引导→解答的完整生命周期。"""

import uuid
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

from core.problem_analyzer import ProblemAnalysis


class SessionState(str, Enum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    GUIDING = "guiding"
    PRAISING = "praising"
    FOLLOW_UP = "follow_up"
    HINTING = "hinting"
    REVEALING = "revealing"
    SUMMARIZING = "summarizing"
    CLOSED = "closed"


class ConversationEntry(BaseModel):
    """对话历史中的一条记录。"""

    role: str  # "system" | "student"
    text: str
    msg_type: str = "guidance"
    hint_level: int | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class PhotoSession(BaseModel):
    """一次拍照引导会话。维护状态机状态、对话历史、引导步骤进度。"""

    session_id: str = Field(default_factory=lambda: f"ps_{uuid.uuid4().hex[:8]}")
    learner_id: str
    state: SessionState = SessionState.IDLE
    problem_analysis: ProblemAnalysis | None = None
    conversation_history: list[ConversationEntry] = Field(default_factory=list)
    current_step: int = 0
    hint_count: int = 0
    attempts_since_last_hint: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_activity: str = Field(default_factory=lambda: datetime.now().isoformat())

    @property
    def solution_steps(self) -> list:
        if self.problem_analysis is None:
            return []
        return self.problem_analysis.solution_steps

    def add_system_message(self, msg_type: str, text: str, hint_level: int | None = None) -> None:
        self.conversation_history.append(ConversationEntry(
            role="system", text=text, msg_type=msg_type, hint_level=hint_level,
        ))
        self._touch()

    def add_student_message(self, text: str) -> None:
        self.conversation_history.append(ConversationEntry(
            role="student", text=text, msg_type="reply",
        ))
        self._touch()

    def increment_attempts_since_last_hint(self) -> None:
        self.attempts_since_last_hint += 1
        self._touch()

    def record_hint(self, level: int) -> None:
        self.hint_count += 1
        self.attempts_since_last_hint = 0
        self.state = SessionState.HINTING
        self._touch()

    def should_reveal(self) -> bool:
        """Level 3 提示后 + 再错 2 次 → 揭示答案"""
        return self.hint_count >= 3 and self.attempts_since_last_hint >= 2

    def complete_current_step(self) -> None:
        self.current_step += 1
        self.hint_count = 0
        self.attempts_since_last_hint = 0
        self._touch()

    def all_steps_completed(self) -> bool:
        return self.current_step >= len(self.solution_steps)

    def _touch(self) -> None:
        self.last_activity = datetime.now().isoformat()

    def is_expired(self, timeout_minutes: int = 30) -> bool:
        last = datetime.fromisoformat(self.last_activity)
        return (datetime.now() - last).total_seconds() > timeout_minutes * 60


import logging

logger = logging.getLogger(__name__)

MAX_CONCURRENT_SESSIONS = 3
SESSION_TIMEOUT_MINUTES = 30


class PhotoSessionManager:
    """管理所有拍照会话的生命周期。"""

    def __init__(self):
        self._sessions: dict[str, PhotoSession] = {}

    def create_session(self, learner_id: str, problem_analysis: "ProblemAnalysis") -> PhotoSession:
        """创建新的拍照会话。"""
        active = self._count_active_for_learner(learner_id)
        if active >= MAX_CONCURRENT_SESSIONS:
            raise ValueError(
                f"Learner {learner_id} 最多 {MAX_CONCURRENT_SESSIONS} 个活跃会话，当前 {active} 个"
            )
        session = PhotoSession(learner_id=learner_id, problem_analysis=problem_analysis)
        self._sessions[session.session_id] = session
        logger.info("Created photo session %s for learner=%s (active=%d/%d)",
                     session.session_id, learner_id, active + 1, MAX_CONCURRENT_SESSIONS)
        return session

    def get_session(self, session_id: str) -> PhotoSession | None:
        """获取会话，不存在返回 None。"""
        return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> None:
        """关闭并移除会话。"""
        removed = self._sessions.pop(session_id, None)
        if removed:
            logger.info("Closed photo session %s", session_id)

    def count_active(self, learner_id: str) -> int:
        """某 learner 的活跃会话数。"""
        return self._count_active_for_learner(learner_id)

    def cleanup_expired(self) -> int:
        """清理所有过期会话，返回清理数量。"""
        expired_ids = [
            sid for sid, s in self._sessions.items()
            if s.is_expired(SESSION_TIMEOUT_MINUTES)
        ]
        for sid in expired_ids:
            self._sessions.pop(sid)
        if expired_ids:
            logger.info("Cleaned up %d expired photo sessions", len(expired_ids))
        return len(expired_ids)

    def _count_active_for_learner(self, learner_id: str) -> int:
        return sum(1 for s in self._sessions.values() if s.learner_id == learner_id)
