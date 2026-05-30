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

TUTOR_SYSTEM = """你是一位耐心、循循善诱的数学老师，正在用苏格拉底式提问引导一位学生解题。

规则：
1. 永远不要直接给出答案或解题步骤
2. 通过提问引导学生自己思考和发现
3. 如果学生回答正确，先肯定，然后引导下一步思考
4. 如果学生回答模糊，温和地追问，帮他表达得更清晰
5. 如果学生卡住或答错，给一个思路提示而不是答案
6. 用口语化的、鼓励的语气，简短回复（50-150字）"""


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
                tutor_msg = self._tutor_response(session, "correct_all_done")
                session.state = SessionState.SUMMARIZING
                session.add_system_message("summary", tutor_msg)
                session.state = SessionState.CLOSED
                return {"action": "summarize", "message": tutor_msg, "session_state": "closed"}
            else:
                next_step = steps[session.current_step]
                session.state = SessionState.GUIDING
                tutor_msg = self._tutor_response(session, "correct_next", next_step)
                session.add_system_message("guidance", tutor_msg)
                return {"action": "praise", "message": tutor_msg, "session_state": session.state.value}
        elif judgement == "partial":
            session.state = SessionState.FOLLOW_UP
            tutor_msg = self._tutor_response(session, "partial")
            session.add_system_message("follow_up", tutor_msg)
            return {"action": "follow_up", "message": tutor_msg, "session_state": session.state.value}
        else:  # wrong
            session.increment_attempts_since_last_hint()
            if session.should_reveal():
                session.state = SessionState.REVEALING
                reveal_text = "\n".join(
                    f"步骤 {s.step_number}: {s.description} — {s.key_insight}"
                    for s in steps
                )
                tutor_msg = self._tutor_response(session, "reveal", reveal_text)
                session.add_system_message("reveal", reveal_text)
                session.state = SessionState.SUMMARIZING
                session.add_system_message("summary", tutor_msg)
                session.state = SessionState.CLOSED
                return {"action": "reveal", "message": f"📝 {reveal_text}\n\n{tutor_msg}", "session_state": "closed"}
            elif session.hint_count >= 3:
                tutor_msg = self._tutor_response(session, "encore")
                session.state = SessionState.HINTING
                session._touch()
                session.add_system_message("hint", tutor_msg, hint_level=3)
                return {"action": "hint", "message": tutor_msg, "hint_level": 3, "session_state": session.state.value}
            else:
                hint_level = session.hint_count + 1
                session.record_hint(hint_level)
                tutor_msg = self._tutor_response(session, "hint", level=hint_level)
                session.add_system_message("hint", tutor_msg, hint_level=hint_level)
                return {"action": "hint", "message": tutor_msg, "hint_level": hint_level, "session_state": session.state.value}

    def _tutor_response(self, session, mode: str, extra=None, level: int = 0) -> str:
        """用 LLM 生成导师回复，根据上下文自然对话。"""
        # 构建对话历史
        history = []
        problem_text = ""
        if session.problem_analysis:
            problem_text = session.problem_analysis.problem_text
        for entry in session.conversation_history[-6:]:  # 最近 6 条
            role = "学生" if entry.role == "student" else "你"
            history.append(f"{role}: {entry.text}")

        context = "\n".join(history)

        if mode == "correct_all_done":
            prompt = f"学生完成了这道题的所有步骤：{problem_text}\n\n对话记录：\n{context}\n\n请简短祝贺并总结学到的知识点，鼓励学生继续练习。"
        elif mode == "correct_next":
            step = extra
            prompt = f"题目：{problem_text}\n\n对话记录：\n{context}\n\n学生答对了当前步骤。下一个要引导的方向是：{step.description}，关键思路：{step.key_insight}\n\n请先肯定学生，然后自然引出下一个引导问题（不要直接给答案）。"
        elif mode == "partial":
            prompt = f"题目：{problem_text}\n\n对话记录：\n{context}\n\n学生回答比较模糊，不够具体。请温和追问，帮他说清楚思路。"
        elif mode == "reveal":
            prompt = f"题目：{problem_text}\n\n对话记录：\n{context}\n\n学生反复尝试后仍然卡住了。完整解题步骤已展示给他。请安慰鼓励，强调理解过程比答案更重要，建议复习相关知识点。"
        elif mode == "encore":
            prompt = f"题目：{problem_text}\n\n对话记录：\n{context}\n\n学生已经收到最高级别的提示但还在努力。请简短鼓励他再试一试，给他信心。"
        elif mode == "hint":
            hint_levels = {1: "元认知层面——提醒学生回忆相关概念，不涉及具体步骤",
                           2: "脚手架层面——给出一个关键思路或第一步，但不给完整解法",
                           3: "详细指导——给出具体解题框架但保留关键计算让学生完成"}
            desc = hint_levels.get(level, "")
            prompt = f"题目：{problem_text}\n\n对话记录：\n{context}\n\n学生卡住了。请提供 L{level} 级别提示（{desc}）。一句话即可，不要给完整答案。"
        else:
            return "继续努力！"

        try:
            from openai import OpenAI
            from config.settings import settings

            if settings.openai_api_key:
                client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
                model = settings.openai_model
            elif settings.minimax_api_key:
                client = OpenAI(api_key=settings.minimax_api_key, base_url="https://api.minimaxi.com/v1")
                model = settings.minimax_model
            else:
                return self._fallback_response(mode, extra)

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": TUTOR_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                timeout=15.0,
            )
            return response.choices[0].message.content or self._fallback_response(mode, extra)
        except Exception:
            return self._fallback_response(mode, extra)

    def _fallback_response(self, mode: str, extra=None) -> str:
        """LLM 不可用时的备用回复。"""
        if mode == "correct_all_done":
            return "🎉 太棒了！你已经完成了这道题的所有步骤。记住这个解题思路，下次遇到类似的题就能用上了！"
        elif mode == "correct_next":
            step = extra
            return f"✅ 很好！那下一步：{step.socratic_prompt}" if extra else "✅ 不错，继续！"
        elif mode == "partial":
            return "你能说得更具体一些吗？试着用数学语言来描述你的思路。"
        elif mode == "reveal":
            return "以上是完整的解题过程。建议你把这道题加入错题本，下次复习时重新做一遍。"
        elif mode == "encore":
            return "💪 再想想，你已经离答案很近了！换个角度试试看。"
        elif mode == "hint":
            return "🤔 回忆一下这道题涉及的核心概念，从你最熟悉的部分开始。"
        return "继续加油！"
