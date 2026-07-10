"""
造浪五力能力框架 — 青少年营地教育的核心能力评估模型。

五个维度：
- 好奇心（Curiosity）：提问、探索、主动尝试
- 创造力（Creativity）：独特想法、动手制作、艺术表达
- 协作力（Collaboration）：团队合作、倾听他人、冲突解决
- 抗逆力（Resilience）：面对困难的态度、坚持、情绪调节
- 表达力（Communication）：分享想法、讲故事、公共表达

评估方法：加权移动平均，每次导师观察以 alpha=0.3 的权重更新评分。

JD 对应：JD 第二条「结合造浪五力能力框架，让 Agent 能对孩子的成长做结构化的记录与反馈」
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ForceDimension(str, Enum):
    """五力维度枚举。"""
    CURIOSITY = "curiosity"
    CREATIVITY = "creativity"
    COLLABORATION = "collaboration"
    RESILIENCE = "resilience"
    COMMUNICATION = "communication"


FORCE_LABELS: dict[ForceDimension, dict[str, str]] = {
    ForceDimension.CURIOSITY: {
        "name": "好奇心",
        "icon": "🔍",
        "description": "对世界保持开放和探索的态度",
        "low_desc": "在熟悉领域内探索，需要引导才能迈出舒适区",
        "mid_desc": "主动尝试新事物，遇到感兴趣的话题会深入追问",
        "high_desc": "自带驱动力地探索未知，能从多个角度提出问题",
    },
    ForceDimension.CREATIVITY: {
        "name": "创造力",
        "icon": "🎨",
        "description": "产生独特想法，用多种方式表达自我",
        "low_desc": "倾向于模仿和跟随，在给定框架内完成任务",
        "mid_desc": "在给定主题下能产生独特想法，有自己的表达风格",
        "high_desc": "主动创造，想法新颖有深度，能在不同媒介间自如切换",
    },
    ForceDimension.COLLABORATION: {
        "name": "协作力",
        "icon": "🤝",
        "description": "在团队中有效合作与沟通",
        "low_desc": "倾向于独立完成任务，需要鼓励才能参与团队",
        "mid_desc": "能配合团队完成任务，在分工中尽责",
        "high_desc": "主动协调团队，能发现并支持他人需求，是自然的团队凝聚者",
    },
    ForceDimension.RESILIENCE: {
        "name": "抗逆力",
        "icon": "💪",
        "description": "面对挑战和失败时保持积极",
        "low_desc": "遇到挫折容易气馁，需要老师鼓励才能继续",
        "mid_desc": "遇到困难会尝试几次，懂得寻求帮助",
        "high_desc": "视挑战为成长机会，失败后能快速调整策略再次尝试",
    },
    ForceDimension.COMMUNICATION: {
        "name": "表达力",
        "icon": "🗣️",
        "description": "清晰表达想法和感受，敢于在公众场合发声",
        "low_desc": "在熟悉的小范围内表达，公开场合较为内向",
        "mid_desc": "能在小组中清晰表达，分享环节可以发言",
        "high_desc": "表达逻辑清晰、生动有趣，能在众人面前自信演讲",
    },
}


class ForceObservation(BaseModel):
    """单次五力观察记录。"""

    dimension: ForceDimension
    score: float = Field(ge=0.0, le=100.0, description="当前评分 0-100")
    evidence: str = Field(description="具体行为描述，如'主动问导师蜗牛为什么只在雨后出现'")
    context: str = Field(default="", description="观察场景，如'森林徒步环节'")
    observer: str = Field(default="", description="观察者/导师名称")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ForceDimensionState(BaseModel):
    """单个五力维度的状态追踪。使用加权移动平均更新评分。"""

    dimension: ForceDimension
    current_score: float = Field(default=25.0, ge=0.0, le=100.0)
    observation_count: int = 0
    alpha: float = Field(default=0.3, description="新观察的权重（0-1），值越大新数据影响越大")

    def add_observation(self, obs: ForceObservation) -> None:
        """加权移动平均更新评分。"""
        self.current_score = (
            (1 - self.alpha) * self.current_score + self.alpha * obs.score
        )
        self.observation_count += 1


class FiveForcesProfile(BaseModel):
    """学员五力画像 — 汇总所有维度的评估数据。"""

    learner_id: str
    dimensions: dict[str, ForceDimensionState] = Field(default_factory=dict)
    observations: list[ForceObservation] = Field(default_factory=list)
    last_updated: str = Field(default_factory=lambda: datetime.now().isoformat())

    def record_observation(self, obs: ForceObservation) -> None:
        """记录一次观察，自动更新对应维度的评分。"""
        dim_key = obs.dimension.value
        if dim_key not in self.dimensions:
            self.dimensions[dim_key] = ForceDimensionState(dimension=obs.dimension)
        self.dimensions[dim_key].add_observation(obs)
        self.observations.append(obs)
        self.last_updated = datetime.now().isoformat()

    def get_score(self, dimension: ForceDimension) -> float:
        """获取某个维度的当前评分。"""
        state = self.dimensions.get(dimension.value)
        return state.current_score if state else 25.0

    def get_level(self, dimension: ForceDimension) -> str:
        """获取某个维度的等级描述。"""
        score = self.get_score(dimension)
        if score < 30:
            return "萌芽期"
        elif score < 55:
            return "成长期"
        elif score < 75:
            return "发展期"
        else:
            return "绽放期"

    def get_level_text(self, dimension: ForceDimension) -> str:
        """获取等级对应的详细描述。"""
        score = self.get_score(dimension)
        labels = FORCE_LABELS[dimension]
        if score < 30:
            return labels["low_desc"]
        elif score < 55:
            return labels["mid_desc"]
        else:
            return labels["high_desc"]

    def get_radar_data(self) -> dict[str, float]:
        """获取雷达图数据（用于前端可视化）。"""
        return {dim.value: self.get_score(dim) for dim in ForceDimension}

    def get_summary(self) -> dict[str, Any]:
        """获取五力摘要（用于报告和 API）。"""
        summary = {}
        for dim in ForceDimension:
            score = self.get_score(dim)
            labels = FORCE_LABELS[dim]
            summary[dim.value] = {
                "name": labels["name"],
                "icon": labels["icon"],
                "score": round(score, 1),
                "level": self.get_level(dim),
                "observation_count": len([
                    o for o in self.observations if o.dimension == dim
                ]),
            }
        if summary:
            sorted_dims = sorted(summary.items(), key=lambda x: x[1]["score"], reverse=True)
            summary["top_strength"] = sorted_dims[0][0]
            summary["growth_area"] = sorted_dims[-1][0]
        return summary

    def get_highlight_observations(self, limit: int = 3) -> list[ForceObservation]:
        """获取最有代表性的观察记录（各维度高分记录）。"""
        if not self.observations:
            return []
        sorted_obs = sorted(self.observations, key=lambda o: o.score, reverse=True)
        seen_dims: set[ForceDimension] = set()
        result = []
        for obs in sorted_obs:
            if obs.dimension not in seen_dims and len(result) < limit:
                result.append(obs)
                seen_dims.add(obs.dimension)
        return result

    def get_dimension_growth(self, dimension: ForceDimension) -> list[dict]:
        """获取某个维度的成长轨迹（时间序列）。"""
        related = [o for o in self.observations if o.dimension == dimension]
        return [
            {"date": o.timestamp, "score": o.score, "evidence": o.evidence}
            for o in related
        ]


def build_default_five_forces_profile(learner_id: str) -> FiveForcesProfile:
    """创建默认的五力画像（所有维度初始 25 分）。"""
    profile = FiveForcesProfile(learner_id=learner_id)
    for dim in ForceDimension:
        profile.dimensions[dim.value] = ForceDimensionState(dimension=dim)
    return profile
