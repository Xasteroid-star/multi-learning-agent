"""题目分析器 -- 将题目文本分解为知识点、难度、解题步骤和引导问题。"""

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SolutionStep(BaseModel):
    """一个解题步骤，包含引导提示。"""

    step_number: int
    description: str
    key_insight: str
    socratic_prompt: str


class ProblemAnalysis(BaseModel):
    """题目完整分析结果。"""

    problem_text: str
    knowledge_points: list[str]
    difficulty: int
    solution_steps: list[SolutionStep]
    relevance_to_weak: float = 0.0


async def analyze_problem(
    problem_text: str,
    student_profile: dict[str, Any],
) -> ProblemAnalysis:
    """分析数学题目，提取知识点、难度和解题步骤。"""
    return await _call_analysis_llm(problem_text, student_profile)


async def _call_analysis_llm(
    problem_text: str,
    student_profile: dict[str, Any],
) -> ProblemAnalysis:
    """调用 LLM 分析题目。生产环境中用真实 API，测试中 mock。"""
    grade = student_profile.get("grade", "初三")
    weak_topics = student_profile.get("weak_topics", [])

    logger.info(
        "Analyzing problem for grade=%s, weak_topics=%s, text length=%d",
        grade, weak_topics, len(problem_text),
    )

    raise NotImplementedError(
        "_call_analysis_llm must be mocked in tests or configured in production"
    )
