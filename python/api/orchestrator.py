"""
Agent 编排器 -- 初始化所有Agent并连接到EventBus。

这是系统的"大脑"，负责：
1. 创建EventBus实例
2. 初始化5个Agent并注入EventBus
3. 提供对外接口供API层调用
"""

from core.event_bus import EventBus, Event, EventType
from core.learner_model import LearnerModel
from agents import (
    AssessmentAgent,
    TutorAgent,
    CurriculumAgent,
    HintAgent,
    EngagementAgent,
)
from agents.photo_tutor_agent import PhotoTutorAgent


class AgentOrchestrator:
    """Agent编排器：管理所有Agent和共享状态。"""

    def __init__(self) -> None:
        self.event_bus = EventBus()
        self.learner_models: dict[str, LearnerModel] = {}

        self.assessment = AssessmentAgent(
            name="AssessmentAgent",
            event_bus=self.event_bus,
            learner_models=self.learner_models,
        )
        self.tutor = TutorAgent(
            name="TutorAgent",
            event_bus=self.event_bus,
            learner_models=self.learner_models,
        )
        self.curriculum = CurriculumAgent(
            name="CurriculumAgent",
            event_bus=self.event_bus,
            learner_models=self.learner_models,
        )
        self.hint = HintAgent(
            name="HintAgent",
            event_bus=self.event_bus,
            learner_models=self.learner_models,
        )
        self.engagement = EngagementAgent(
            name="EngagementAgent",
            event_bus=self.event_bus,
            learner_models=self.learner_models,
        )
        self.photo_tutor = PhotoTutorAgent(
            name="PhotoTutorAgent",
            event_bus=self.event_bus,
            learner_models=self.learner_models,
        )

    async def submit_answer(
        self, learner_id: str, knowledge_id: str, is_correct: bool, time_spent: float = 0
    ) -> list[Event]:
        """学生提交答案 -> 触发完整的Agent处理链。"""
        event = Event(
            type=EventType.STUDENT_SUBMISSION,
            source="api",
            learner_id=learner_id,
            data={
                "knowledge_id": knowledge_id,
                "is_correct": is_correct,
                "time_spent_seconds": time_spent,
            },
        )
        await self.event_bus.publish(event)
        return self.event_bus.get_history(learner_id=learner_id, limit=20)

    async def ask_question(
        self, learner_id: str, knowledge_id: str, question: str
    ) -> list[Event]:
        """学生提问 -> 触发Assessment + Tutor处理。"""
        event = Event(
            type=EventType.STUDENT_QUESTION,
            source="api",
            learner_id=learner_id,
            data={"knowledge_id": knowledge_id, "question": question},
        )
        await self.event_bus.publish(event)
        return self.event_bus.get_history(learner_id=learner_id, limit=20)

    async def send_message(
        self, learner_id: str, message: str, knowledge_id: str = "general"
    ) -> list[Event]:
        """学生发送消息 -> 触发Tutor对话。"""
        event = Event(
            type=EventType.STUDENT_MESSAGE,
            source="api",
            learner_id=learner_id,
            data={"message": message, "knowledge_id": knowledge_id},
        )
        await self.event_bus.publish(event)
        return self.event_bus.get_history(learner_id=learner_id, limit=20)

    def get_learner_progress(self, learner_id: str) -> dict:
        """获取学习者进度。"""
        if learner_id not in self.learner_models:
            return {"learner_id": learner_id, "status": "no_data"}
        model = self.learner_models[learner_id]
        return {
            "learner_id": learner_id,
            "progress": model.get_overall_progress(),
            "weak_points": [
                {"id": s.knowledge_id, "mastery": s.mastery}
                for s in model.get_weak_points()
            ],
            "strong_points": [
                {"id": s.knowledge_id, "mastery": s.mastery}
                for s in model.get_strong_points()
            ],
        }

    def create_photo_session(self, learner_id: str, problem_analysis) -> str:
        """创建拍照引导会话，返回 session_id。"""
        from core.photo_session import SessionState
        session = self.photo_tutor.session_manager.create_session(
            learner_id, problem_analysis
        )
        session.state = SessionState.ANALYZING
        return session.session_id

    def submit_photo_reply(self, session_id: str, learner_id: str, reply: str) -> dict | None:
        """处理学生对引导问题的回复，返回下一步操作。"""
        session = self.photo_tutor.session_manager.get_session(session_id)
        if session is None:
            return None

        from core.photo_session import SessionState

        session.add_student_message(reply)

        current_step_idx = session.current_step
        steps = session.solution_steps
        if current_step_idx < len(steps):
            step = steps[current_step_idx]
            keywords = set(step.key_insight.split()) | {step.description}
        else:
            keywords = set()

        judgement = self.photo_tutor._judge_reply(reply, keywords)

        if judgement == "correct":
            session.state = SessionState.PRAISING
            session.complete_current_step()
            if session.all_steps_completed():
                session.state = SessionState.SUMMARIZING
                session.add_system_message("summary", "🎉 太棒了！你已经完成了这道题的所有步骤。")
                session.state = SessionState.CLOSED
                return {
                    "action": "summarize",
                    "message": "🎉 太棒了！你已经完成了这道题的所有步骤。",
                    "session_state": session.state.value,
                }
            else:
                next_step = steps[session.current_step]
                session.state = SessionState.GUIDING
                session.add_system_message("guidance", next_step.socratic_prompt)
                return {
                    "action": "praise",
                    "message": f"✅ 正确！{next_step.socratic_prompt}",
                    "session_state": session.state.value,
                }
        elif judgement == "partial":
            session.state = SessionState.FOLLOW_UP
            session.add_system_message("follow_up", "你能说得更具体一些吗？试着用数学语言描述。")
            return {
                "action": "follow_up",
                "message": "你能说得更具体一些吗？试着用数学语言描述。",
                "session_state": session.state.value,
            }
        else:  # wrong
            session.increment_attempts_since_last_hint()
            if session.should_reveal():
                session.state = SessionState.REVEALING
                reveal_text = "\n".join(
                    f"步骤 {s.step_number}: {s.description} — {s.key_insight}"
                    for s in steps
                )
                session.add_system_message("reveal", reveal_text)
                session.state = SessionState.SUMMARIZING
                session.add_system_message(
                    "summary",
                    "以上是完整的解题过程。建议你把这道题加入错题本，下次复习时重新做一遍。",
                )
                session.state = SessionState.CLOSED
                return {
                    "action": "reveal",
                    "message": f"📝 完整解题过程：\n{reveal_text}\n\n建议加入错题本复习。",
                    "session_state": "closed",
                }
            elif session.hint_count >= 3:
                # Already maxed out hints; let attempts accumulate without resetting
                encore_msg = "再想想，你可以的！"
                session.state = SessionState.HINTING
                session._touch()
                session.add_system_message("hint", encore_msg, hint_level=3)
                return {
                    "action": "hint",
                    "message": encore_msg,
                    "hint_level": 3,
                    "session_state": session.state.value,
                }
            else:
                hint_level = session.hint_count + 1
                session.record_hint(hint_level)
                hint_text = self._generate_hint_text(hint_level, steps[current_step_idx].description)
                session.add_system_message("hint", hint_text, hint_level=hint_level)
                return {
                    "action": "hint",
                    "message": hint_text,
                    "hint_level": hint_level,
                    "session_state": session.state.value,
                }

    def _generate_hint_text(self, level: int, step_description: str) -> str:
        """基于级别生成提示文本。"""
        if level == 1:
            return f"💡 提示 L1：试着回忆一下和「{step_description}」相关的基础概念。"
        elif level == 2:
            return f"📝 提示 L2：这道题的关键在于「{step_description}」，你先试试看第一步。"
        else:
            return f"📖 提示 L3：好的，让我给你更详细的指导。{step_description}。"
