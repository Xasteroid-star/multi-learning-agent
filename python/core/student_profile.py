"""学生画像 -- 记录学生基础信息和学习偏好，与 LearnerModel (BKT) 互补。"""

from datetime import datetime
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
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
