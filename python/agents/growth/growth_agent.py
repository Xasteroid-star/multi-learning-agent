"""
学员成长 Agent — 从 0 到 1 追踪每位学员的完整成长轨迹。

职责：
1. 聚合多源数据：拍照解题、五力观察、作品记录、导师点评
2. 维护学员的「成长时间线」
3. 检测关键成长节点和突破时刻
4. 为报告生成提供结构化数据

JD 对应：JD 第二条「为每位学员设计并搭建一个成长 Agent」
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.event_bus import Event, EventBus, EventType
from core.learner_model import LearnerModel
from core.five_forces_model import ForceDimension, ForceObservation
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class GrowthEvent(BaseModel):
    """成长事件 — 记录学员成长过程中的一个节点。"""

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    learner_id: str
    event_type: str  # "observation", "milestone", "project", "feedback", "checkpoint"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    title: str
    description: str
    related_dimensions: list[str] = Field(default_factory=list)
    evidence: str = ""
    media_urls: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class GrowthTimeline(BaseModel):
    """成长时间线 — 按时间排列的成长事件集合。"""

    learner_id: str
    events: list[GrowthEvent] = Field(default_factory=list)
    milestones: list[dict] = Field(default_factory=list)
    camp_sessions: list[dict] = Field(default_factory=list)

    def add_event(self, event: GrowthEvent) -> None:
        self.events.append(event)

    def add_milestone(self, title: str, description: str, date: str | None = None) -> None:
        self.milestones.append({
            "title": title,
            "description": description,
            "date": date or datetime.now().isoformat(),
        })

    def get_events_by_camp(self, camp_name: str) -> list[GrowthEvent]:
        return [e for e in self.events if camp_name in e.tags]

    def get_recent_events(self, days: int = 30) -> list[GrowthEvent]:
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return [e for e in self.events if e.timestamp >= cutoff]

    def get_dimension_growth(self, dimension: str) -> list[dict]:
        """获取某个维度的成长轨迹（时间序列）。"""
        related = [e for e in self.events if dimension in e.related_dimensions]
        return [
            {"date": e.timestamp, "title": e.title, "description": e.description}
            for e in related
        ]


class GrowthAgent(BaseAgent):
    """学员成长 Agent — 订阅学习事件，持续追踪成长。"""

    def __init__(self, name: str, event_bus: EventBus,
                 learner_models: dict[str, LearnerModel]) -> None:
        super().__init__(name, event_bus, learner_models)
        self._timelines: dict[str, GrowthTimeline] = {}

    @property
    def subscribed_events(self) -> list[EventType]:
        return [
            EventType.ASSESSMENT_COMPLETE,
            EventType.MASTERY_UPDATED,
            EventType.PHOTO_SESSION_STARTED,
            EventType.STUDENT_SUBMISSION,
            EventType.STUDENT_QUESTION,
            EventType.ENGAGEMENT_ALERT,
        ]

    async def handle_event(self, event: Event) -> None:
        learner_id = event.learner_id

        if event.type == EventType.PHOTO_SESSION_STARTED:
            self._record_event(learner_id, GrowthEvent(
                learner_id=learner_id,
                event_type="checkpoint",
                title="发起一次拍照学习",
                description="学员自主发起了一次学习探索",
                related_dimensions=["curiosity"],
                tags=["learning", "self_initiated"],
            ))

        elif event.type == EventType.MASTERY_UPDATED:
            data = event.data or {}
            knowledge_id = data.get("knowledge_id", "")
            new_mastery = data.get("new_mastery", 0)
            old_mastery = data.get("old_mastery", 0)

            if new_mastery > 0.85 and old_mastery < 0.85:
                self._record_event(learner_id, GrowthEvent(
                    learner_id=learner_id,
                    event_type="milestone",
                    title=f"掌握新知识点",
                    description=f"在 {knowledge_id} 上达到掌握水平 ({new_mastery:.0%})",
                    related_dimensions=["resilience", "curiosity"],
                    tags=["mastery", knowledge_id],
                ))

        elif event.type == EventType.ENGAGEMENT_ALERT:
            data = event.data or {}
            alert_type = data.get("alert_type", "")
            if alert_type == "frustration_recovery":
                self._record_event(learner_id, GrowthEvent(
                    learner_id=learner_id,
                    event_type="milestone",
                    title="克服困难时刻",
                    description="在遇到挫折后坚持并最终成功",
                    related_dimensions=["resilience"],
                    tags=["grit", "growth"],
                ))

    def _record_event(self, learner_id: str, event: GrowthEvent) -> None:
        if learner_id not in self._timelines:
            self._timelines[learner_id] = GrowthTimeline(learner_id=learner_id)
        self._timelines[learner_id].add_event(event)
        logger.info("[GrowthAgent] Recorded event for %s: %s", learner_id, event.title)

    def get_timeline(self, learner_id: str) -> GrowthTimeline:
        """获取学员成长时间线。"""
        if learner_id not in self._timelines:
            self._timelines[learner_id] = GrowthTimeline(learner_id=learner_id)
        return self._timelines[learner_id]

    def add_manual_observation(
        self, learner_id: str, dimension: str, score: float,
        evidence: str, context: str = "", observer: str = "",
    ) -> ForceObservation:
        """手动添加导师观察（用于营地场景中导师的日常记录）。

        同时更新 BKT LearnerModel 中的五力画像和成长时间线。
        返回创建的 ForceObservation。
        """
        try:
            dim = ForceDimension(dimension)
        except ValueError:
            dim = ForceDimension.CURIOSITY
            logger.warning("Unknown dimension '%s', defaulting to curiosity", dimension)

        obs = ForceObservation(
            dimension=dim,
            score=score,
            evidence=evidence,
            context=context,
            observer=observer,
        )

        # 更新 LearnerModel 中的五力画像
        learner = self.get_learner_model(learner_id)
        learner.five_forces.record_observation(obs)

        # 记录到成长时间线
        labels = __import__("core.five_forces_model", fromlist=["FORCE_LABELS"]).FORCE_LABELS
        force_name = labels.get(dim, {}).get("name", dimension)

        self._record_event(learner_id, GrowthEvent(
            learner_id=learner_id,
            event_type="observation",
            title=f"{force_name} 观察记录",
            description=evidence,
            related_dimensions=[dimension],
            evidence=evidence,
            tags=["observation", dimension, observer],
        ))

        # 持久化到 ProfileStore（防止重启丢失）
        # 如果画像不存在则自动创建，确保五力数据始终持久化
        try:
            from core.student_profile import ProfileStore, StudentProfile
            store = ProfileStore()
            import asyncio
            async def _persist():
                await store.init_db()
                existing = await store.load(learner_id)
                if existing is None:
                    # 自动创建画像
                    existing = StudentProfile(
                        learner_id=learner_id, name=learner_id, grade="未知",
                    )
                existing = await ProfileStore.refresh_from_bkt(existing, learner)
                await store.save(existing)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_persist())
            except RuntimeError:
                asyncio.run(_persist())
        except Exception as e:
            logger.warning("Failed to persist forces for %s: %s", learner_id, e)

        logger.info(
            "[GrowthAgent] Recorded observation for %s: %s score=%.1f",
            learner_id, dimension, score,
        )
        return obs

    def add_project_record(
        self, learner_id: str, project_name: str, description: str,
        related_dimensions: list[str], media_urls: list[str] | None = None,
    ) -> None:
        """记录学员的项目/作品。"""
        self._record_event(learner_id, GrowthEvent(
            learner_id=learner_id,
            event_type="project",
            title=project_name,
            description=description,
            related_dimensions=related_dimensions,
            media_urls=media_urls or [],
            tags=["project"] + related_dimensions,
        ))

    # ── 行为信号追踪 (Trend 2: Behavioral Evaluation) ──
    # 核心洞察：学生收到反馈后做了什么，比反馈本身更能预测学习效果
    # 参考: "The Missing Evaluation Axis" (arXiv:2605.05648)

    def record_hint_given(self, learner_id: str, hint_level: int,
                          problem_context: str = "") -> None:
        """记录一次提示被给出——标记行为追踪的起点。"""
        snapshot = {
            "type": "hint_snapshot",
            "hint_level": hint_level,
            "problem": problem_context,
            "timestamp": datetime.now().isoformat(),
        }
        self._record_event(learner_id, GrowthEvent(
            learner_id=learner_id,
            event_type="checkpoint",
            title=f"收到 L{hint_level} 提示",
            description=problem_context or "学生在解题中收到提示",
            related_dimensions=["resilience"],
            evidence=problem_context,
            tags=["behavior", "hint_received", f"L{hint_level}"],
        ))

    def record_hint_outcome(self, learner_id: str, hint_level: int,
                            was_helpful: bool, attempts_after: int,
                            eventually_solved: bool) -> dict:
        """记录提示的结果——行为追踪的终点。

        Returns behavioral metrics for this hint cycle.

        参考论文核心发现：
        - 反馈后学生是否尝试了（persistence）
        - 反馈后学生是否改进了（improvement）
        - 这两个信号比反馈质量更能预测学生的满意度
        """
        # 计算行为得分
        behavior_score = 0.0
        if was_helpful:
            behavior_score += 40
        if attempts_after > 0:
            behavior_score += 30  # persistence
        if eventually_solved:
            behavior_score += 30  # improvement

        # 自动更新抗逆力——这是从行为数据中推导的客观信号
        try:
            learner = self.get_learner_model(learner_id)
            learner.record_force_observation(
                dimension="resilience",
                score=behavior_score,
                evidence=(
                    f"收到 L{hint_level} 提示后{'采纳并改进' if was_helpful else '仍在尝试'}，"
                    f"共尝试 {attempts_after} 次，"
                    f"{'最终解出' if eventually_solved else '仍在努力'}"
                ),
                context=f"提示反馈追踪 L{hint_level}",
                observer="BehavioralTracker",
            )
        except Exception as e:
            logger.warning("Failed to update force from behavior: %s", e)

        metrics = {
            "learner_id": learner_id,
            "hint_level": hint_level,
            "was_helpful": was_helpful,
            "attempts_after": attempts_after,
            "eventually_solved": eventually_solved,
            "behavior_score": behavior_score,
        }

        self._record_event(learner_id, GrowthEvent(
            learner_id=learner_id,
            event_type="feedback",
            title=f"提示结果: {'有效 ✅' if was_helpful else '继续尝试'}",
            description=(
                f"L{hint_level} 提示{'帮助了学生' if was_helpful else '未完全解决'}"
                f"，之后尝试 {attempts_after} 次"
                f"{'，最终解出' if eventually_solved else ''}"
            ),
            related_dimensions=["resilience"],
            evidence=str(metrics),
            tags=["behavior", "hint_outcome", f"score_{int(behavior_score)}"],
        ))

        return metrics

    def get_behavioral_summary(self, learner_id: str) -> dict:
        """获取学员的行为信号摘要——用于报告和教师仪表盘。"""
        timeline = self.get_timeline(learner_id)
        all_events = timeline.events

        hint_received = [e for e in all_events if "hint_received" in e.tags]
        hint_outcomes = [e for e in all_events if "hint_outcome" in e.tags]

        # 计算指标
        total_hints = len(hint_received)
        helpful_hints = sum(
            1 for e in hint_outcomes
            if "有效" in e.title
        )
        persistence_events = [
            e for e in all_events
            if e.event_type == "milestone" and "克服困难" in e.title
        ]

        return {
            "learner_id": learner_id,
            "total_hints_received": total_hints,
            "hint_effectiveness_rate": (
                round(helpful_hints / len(hint_outcomes) * 100, 1)
                if hint_outcomes else 0
            ),
            "feedback_adoption_rate": round(
                helpful_hints / max(total_hints, 1) * 100, 1
            ),
            "persistence_moments": len(persistence_events),
            "total_learning_events": len(all_events),
            # 行为信号驱动的洞察
            "behavioral_insight": (
                "学生收到反馈后倾向于采纳并改进"
                if helpful_hints > total_hints * 0.5
                else "学生收到反馈后需要更多鼓励才会尝试"
            ) if total_hints > 0 else "尚未有足够的反馈数据",
        }
