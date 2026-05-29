"""题目分析器 -- 将题目文本分解为知识点、难度、解题步骤和引导问题。"""

from pydantic import BaseModel


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
