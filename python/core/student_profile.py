"""学生画像 -- 记录学生基础信息和学习偏好，与 LearnerModel (BKT) 互补。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class StudentProfile(BaseModel):
    """学生画像。"""

    learner_id: str
    name: str
    grade: str  # "初一" ~ "高三"
    learning_style: str = "mixed"  # "visual" | "textual" | "mixed"
    preferred_pace: str = "normal"  # "fast" | "normal" | "slow"
    total_sessions: int = 0
    total_photo_solves: int = 0
    weak_topics: list[str] = Field(default_factory=list)
    strong_topics: list[str] = Field(default_factory=list)
    recent_activity: list[dict] = Field(default_factory=list)
    # 五力模型字段
    curiosity_score: float = 25.0
    creativity_score: float = 25.0
    collaboration_score: float = 25.0
    resilience_score: float = 25.0
    communication_score: float = 25.0
    force_observations_count: int = 0
    camp_history: list[dict] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


import json
import logging
import aiosqlite

logger = logging.getLogger(__name__)


class ProfileStore:
    """SQLite 持久化的学生画像存储。"""

    def __init__(self, db_path: str = "data/student_profiles.db"):
        self.db_path = db_path

    async def init_db(self) -> None:
        """创建表（如果不存在）。"""
        import os
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS student_profiles (
                    learner_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    grade TEXT NOT NULL DEFAULT '初三',
                    learning_style TEXT NOT NULL DEFAULT 'mixed',
                    preferred_pace TEXT NOT NULL DEFAULT 'normal',
                    total_sessions INTEGER NOT NULL DEFAULT 0,
                    total_photo_solves INTEGER NOT NULL DEFAULT 0,
                    weak_topics TEXT NOT NULL DEFAULT '[]',
                    strong_topics TEXT NOT NULL DEFAULT '[]',
                    recent_activity TEXT NOT NULL DEFAULT '[]',
                    curiosity_score REAL NOT NULL DEFAULT 25.0,
                    creativity_score REAL NOT NULL DEFAULT 25.0,
                    collaboration_score REAL NOT NULL DEFAULT 25.0,
                    resilience_score REAL NOT NULL DEFAULT 25.0,
                    communication_score REAL NOT NULL DEFAULT 25.0,
                    force_observations_count INTEGER NOT NULL DEFAULT 0,
                    camp_history TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            await db.commit()
        logger.info("ProfileStore database initialized at %s", self.db_path)

    async def save(self, profile: "StudentProfile") -> None:
        """保存或更新学生画像。"""
        weak_json = json.dumps(profile.weak_topics, ensure_ascii=False)
        strong_json = json.dumps(profile.strong_topics, ensure_ascii=False)
        activity_json = json.dumps(profile.recent_activity, ensure_ascii=False)
        camp_json = json.dumps(profile.camp_history, ensure_ascii=False)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO student_profiles
                    (learner_id, name, grade, learning_style, preferred_pace,
                     total_sessions, total_photo_solves,
                     weak_topics, strong_topics, recent_activity,
                     curiosity_score, creativity_score, collaboration_score,
                     resilience_score, communication_score, force_observations_count,
                     camp_history,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?)
                ON CONFLICT(learner_id) DO UPDATE SET
                    name = excluded.name,
                    grade = excluded.grade,
                    learning_style = excluded.learning_style,
                    preferred_pace = excluded.preferred_pace,
                    total_sessions = excluded.total_sessions,
                    total_photo_solves = excluded.total_photo_solves,
                    weak_topics = excluded.weak_topics,
                    strong_topics = excluded.strong_topics,
                    recent_activity = excluded.recent_activity,
                    curiosity_score = excluded.curiosity_score,
                    creativity_score = excluded.creativity_score,
                    collaboration_score = excluded.collaboration_score,
                    resilience_score = excluded.resilience_score,
                    communication_score = excluded.communication_score,
                    force_observations_count = excluded.force_observations_count,
                    camp_history = excluded.camp_history,
                    updated_at = excluded.updated_at
                """,
                (
                    profile.learner_id, profile.name, profile.grade,
                    profile.learning_style, profile.preferred_pace,
                    profile.total_sessions, profile.total_photo_solves,
                    weak_json, strong_json, activity_json,
                    profile.curiosity_score, profile.creativity_score,
                    profile.collaboration_score, profile.resilience_score,
                    profile.communication_score, profile.force_observations_count,
                    camp_json,
                    profile.created_at, profile.updated_at,
                ),
            )
            await db.commit()
        logger.info("Saved profile for learner=%s", profile.learner_id)

    async def load(self, learner_id: str) -> Optional["StudentProfile"]:
        """加载学生画像。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM student_profiles WHERE learner_id = ?", (learner_id,),
            ) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return None

        return StudentProfile(
            learner_id=row["learner_id"], name=row["name"], grade=row["grade"],
            learning_style=row["learning_style"], preferred_pace=row["preferred_pace"],
            total_sessions=row["total_sessions"], total_photo_solves=row["total_photo_solves"],
            weak_topics=json.loads(row["weak_topics"]),
            strong_topics=json.loads(row["strong_topics"]),
            recent_activity=json.loads(row["recent_activity"]),
            curiosity_score=row["curiosity_score"],
            creativity_score=row["creativity_score"],
            collaboration_score=row["collaboration_score"],
            resilience_score=row["resilience_score"],
            communication_score=row["communication_score"],
            force_observations_count=row["force_observations_count"],
            camp_history=json.loads(row["camp_history"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    async def refresh_from_bkt(
        profile: "StudentProfile", learner_model: "LearnerModel",
    ) -> "StudentProfile":
        """从 BKT LearnerModel 刷新 weak_topics、strong_topics 和五力数据。不会自动保存。"""
        weak = learner_model.get_weak_points(threshold=0.4, limit=10)
        strong = learner_model.get_strong_points(threshold=0.85)
        profile.weak_topics = [s.knowledge_id for s in weak]
        profile.strong_topics = [s.knowledge_id for s in strong]

        # 同步五力数据到 profile
        from core.five_forces_model import ForceDimension
        forces = learner_model.five_forces
        profile.curiosity_score = forces.get_score(ForceDimension.CURIOSITY)
        profile.creativity_score = forces.get_score(ForceDimension.CREATIVITY)
        profile.collaboration_score = forces.get_score(ForceDimension.COLLABORATION)
        profile.resilience_score = forces.get_score(ForceDimension.RESILIENCE)
        profile.communication_score = forces.get_score(ForceDimension.COMMUNICATION)
        profile.force_observations_count = len(forces.observations)
        profile.updated_at = datetime.now().isoformat()
        return profile

    @staticmethod
    def load_forces_into_model(profile: "StudentProfile", learner_model: "LearnerModel") -> None:
        """将 ProfileStore 中持久化的五力数据恢复到 LearnerModel 的内存中。

        在服务器启动 / 首次加载学员时调用，确保重启后数据不丢失。
        """
        from core.five_forces_model import ForceDimension, ForceObservation
        forces = learner_model.five_forces

        # 直接用已持久化的分数覆盖默认值
        score_map = {
            ForceDimension.CURIOSITY: profile.curiosity_score,
            ForceDimension.CREATIVITY: profile.creativity_score,
            ForceDimension.COLLABORATION: profile.collaboration_score,
            ForceDimension.RESILIENCE: profile.resilience_score,
            ForceDimension.COMMUNICATION: profile.communication_score,
        }
        for dim, score in score_map.items():
            state = forces.dimensions.get(dim.value)
            if state:
                state.current_score = score
                state.observation_count = profile.force_observations_count
        from datetime import datetime
        profile.updated_at = datetime.now().isoformat()
        return profile
