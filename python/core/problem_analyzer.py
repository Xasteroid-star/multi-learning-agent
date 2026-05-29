"""题目分析器 -- 将题目文本分解为知识点、难度、解题步骤和引导问题。"""

import json
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


ANALYSIS_PROMPT = """你是一位资深的K12数学老师。请分析下面的数学题目，输出严格的JSON格式。

题目：
{problem_text}

学生年级：{grade}
学生薄弱知识点：{weak_topics}

请输出以下JSON结构（不要输出其他内容）：
```json
{{
  "knowledge_points": ["知识点1", "知识点2"],
  "difficulty": 3,
  "solution_steps": [
    {{
      "step_number": 1,
      "description": "这步做什么",
      "key_insight": "核心思路关键词",
      "socratic_prompt": "引导式提问，引导思考"
    }}
  ],
  "relevance_to_weak": 0.5
}}
```

要求：
1. knowledge_points: 列出这道题涉及的2-5个核心知识点（中文名称）
2. difficulty: 1-5的难度评级（1=基础，3=中等，5=困难）
3. solution_steps: 拆解为2-5个解题步骤，每步包含：
   - description: 这步做什么（简短描述）
   - key_insight: 核心思路关键词（用于判断学生回复是否触及要点，用空格分隔）
   - socratic_prompt: 一个不直接给答案的引导式提问
4. relevance_to_weak: 0.0-1.0，题目与薄弱知识点的关联程度
5. 步骤顺序要合理，从易到难
6. 只输出JSON，不要解释"""


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
    """调用 LLM 分析题目。"""
    from config.settings import settings
    from openai import OpenAI

    grade = student_profile.get("grade", "初三")
    weak_topics = student_profile.get("weak_topics", [])
    weak_str = ", ".join(weak_topics) if weak_topics else "无"

    logger.info("Analyzing problem for grade=%s, weak_topics=%s, text length=%d",
                 grade, weak_topics, len(problem_text))

    # OpenAI 优先，MiniMax 备用
    if settings.openai_api_key:
        client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        model = settings.openai_model
        provider = "openai"
    elif settings.minimax_api_key:
        client = OpenAI(api_key=settings.minimax_api_key, base_url="https://api.minimaxi.com/v1")
        model = settings.minimax_model
        provider = "minimax"
    else:
        logger.warning("No LLM API key configured — returning fallback")
        return ProblemAnalysis(
            problem_text=problem_text,
            knowledge_points=["未识别"],
            difficulty=3,
            solution_steps=[
                SolutionStep(
                    step_number=1, description="分析题目",
                    key_insight="识别已知条件和求解目标",
                    socratic_prompt="你能告诉我这道题的已知条件是什么，要求什么吗？",
                ),
            ],
            relevance_to_weak=0.0,
        )

    logger.info("Analysis using %s provider with model=%s", provider, model)

    prompt = ANALYSIS_PROMPT.format(
        problem_text=problem_text,
        grade=grade,
        weak_topics=weak_str,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一位资深的K12数学老师。请只输出JSON，不要有其他内容。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        raw = response.choices[0].message.content or ""
        logger.info("Analysis LLM response: %s", raw[:300])
    except Exception as e:
        logger.exception("Analysis LLM call failed")
        return ProblemAnalysis(
            problem_text=problem_text,
            knowledge_points=["分析失败"],
            difficulty=3,
            solution_steps=[
                SolutionStep(
                    step_number=1,
                    description="请重试",
                    key_insight="错误",
                    socratic_prompt=f"分析出错：{e}，请重试",
                ),
            ],
            relevance_to_weak=0.0,
        )

    # Parse JSON from LLM response
    try:
        # handle ```json wrappers
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]

        data = json.loads(raw)
        steps = [SolutionStep(**s) for s in data.get("solution_steps", [])]

        return ProblemAnalysis(
            problem_text=problem_text,
            knowledge_points=data.get("knowledge_points", ["未识别"]),
            difficulty=data.get("difficulty", 3),
            solution_steps=steps,
            relevance_to_weak=data.get("relevance_to_weak", 0.0),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.exception("Failed to parse LLM analysis response")
        return ProblemAnalysis(
            problem_text=problem_text,
            knowledge_points=["解析错误"],
            difficulty=3,
            solution_steps=[
                SolutionStep(
                    step_number=1,
                    description="分析题目",
                    key_insight="尝试分析",
                    socratic_prompt="让我们重新开始，你能描述一下这道题吗？",
                ),
            ],
            relevance_to_weak=0.0,
        )
