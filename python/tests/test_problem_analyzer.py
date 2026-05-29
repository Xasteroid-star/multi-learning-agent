"""Problem Analyzer 测试。"""

from unittest.mock import AsyncMock, patch

import pytest
from core.problem_analyzer import ProblemAnalysis, SolutionStep, analyze_problem


def test_solution_step_creation():
    """SolutionStep 应该能正确创建"""
    step = SolutionStep(
        step_number=1,
        description="将一般式化为顶点式",
        key_insight="配方法的关键是把一次项系数除2再平方",
        socratic_prompt="你能把 x²+2x-3 写成完全平方形式吗？",
    )
    assert step.step_number == 1
    assert "配方法" in step.key_insight
    assert step.socratic_prompt.startswith("你能")


def test_problem_analysis_creation():
    """ProblemAnalysis 应该包含完整的解题步骤"""
    steps = [
        SolutionStep(
            step_number=1,
            description="识别函数类型",
            key_insight="标准形式 f(x)=ax²+bx+c",
            socratic_prompt="这是哪种类型的函数？它的标准形式是什么？",
        ),
        SolutionStep(
            step_number=2,
            description="求顶点坐标",
            key_insight="顶点公式 x=-b/(2a)",
            socratic_prompt="二次函数的顶点横坐标公式是什么？",
        ),
    ]
    analysis = ProblemAnalysis(
        problem_text="已知二次函数 f(x)=x²+2x-3，求其顶点坐标",
        knowledge_points=["二次函数顶点式", "配方法"],
        difficulty=3,
        solution_steps=steps,
        relevance_to_weak=0.8,
    )
    assert len(analysis.solution_steps) == 2
    assert analysis.knowledge_points == ["二次函数顶点式", "配方法"]
    assert analysis.difficulty == 3
    assert analysis.relevance_to_weak == 0.8


def test_solution_step_defaults():
    """SolutionStep 数值默认值"""
    step = SolutionStep(
        step_number=1,
        description="test",
        key_insight="test",
        socratic_prompt="test?",
    )
    assert step.step_number == 1


@pytest.mark.asyncio
async def test_analyze_problem_returns_structured_result():
    """analyze_problem 应返回完整的 ProblemAnalysis"""
    problem_text = "已知二次函数 f(x)=x²+2x-3，求其顶点坐标"
    student_profile = {"learner_id": "u1", "grade": "高一", "weak_topics": ["配方法"]}

    with patch("core.problem_analyzer._call_analysis_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = ProblemAnalysis(
            problem_text=problem_text,
            knowledge_points=["二次函数顶点式", "配方法"],
            difficulty=3,
            solution_steps=[
                SolutionStep(step_number=1, description="识别函数类型", key_insight="标准形式 f(x)=ax²+bx+c", socratic_prompt="这是哪种类型的函数？"),
                SolutionStep(step_number=2, description="求顶点坐标", key_insight="顶点公式 x=-b/(2a)", socratic_prompt="二次函数的顶点横坐标公式是什么？"),
            ],
            relevance_to_weak=0.8,
        )
        result = await analyze_problem(problem_text, student_profile)

    assert len(result.knowledge_points) == 2
    assert "配方法" in result.knowledge_points
    assert len(result.solution_steps) == 2
    assert result.relevance_to_weak > 0


@pytest.mark.asyncio
async def test_analyze_problem_prioritizes_weak_topics():
    """弱项知识点应获得更高的 relevance_to_weak"""
    problem_text = "求解一元二次方程 x² - 5x + 6 = 0"
    student_profile = {"learner_id": "u1", "grade": "初三", "weak_topics": ["因式分解法", "配方法"]}

    with patch("core.problem_analyzer._call_analysis_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = ProblemAnalysis(
            problem_text=problem_text,
            knowledge_points=["因式分解法", "一元二次方程"],
            difficulty=2,
            solution_steps=[SolutionStep(step_number=1, description="因式分解", key_insight="交叉相乘", socratic_prompt="试试因式分解？")],
            relevance_to_weak=0.9,
        )
        result = await analyze_problem(problem_text, student_profile)

    assert result.relevance_to_weak == 0.9
