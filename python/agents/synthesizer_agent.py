"""
Synthesizer Agent — ITAS 模式的核心：融合多 Agent 输出为一段连贯的自然对话。

架构（参考 ITAS, arXiv:2604.24808）：
    AssessmentAgent ──┐
    TutorAgent ────────┼──→ SynthesizerAgent ──→ 一段自然的导师回复
    HintAgent ────────┘

关键设计（来自 ITAS 论文）：
1. "轮辐式"三层并行 → 合成器整合，不是简单拼接而是自然编织
2. 合成器知道每个输入的专业角色，按教学逻辑重组
3. 包含「安全边界检查」——防止合成后的回复越界（如直接给答案）
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SYNTHESIZER_SYSTEM = """你是一位经验丰富的教育导师，正在与学生进行一对一对话。

你的任务是把三份专业的教学分析，融合成一段自然、温暖、连贯的回复。

输入格式：
- 【学情评估】来自评估系统：学生当前的知识掌握状态
- 【教学引导】来自教学系统：下一步应该引导学生思考什么
- 【提示建议】来自提示系统：如果学生卡住了，用什么级别的提示（L1=元认知/L2=脚手架/L3=详细）

合成规则：
1. **语气自然**：不能听起来像三段拼接，要像一位老师在自然地说话
2. **学情嵌入**：在不经意间融入学情信息，比如"你刚才对函数部分理解得很好，现在试试这个角度…"
3. **引导优先**：以苏格拉底式提问为主线，不要直接给答案
4. **提示嵌入**：如果需要提示，自然地织入对话，不要生硬地标注"这是L2提示"
5. **长度控制**：50-150字，简洁有力
6. **安全底线**：绝对不能直接给出完整答案或解题步骤

输出：一段自然的中文对话回复，不要加任何前缀标记。"""


class AgentInput(BaseModel):
    """单个 Agent 的输入——来自一个专业 Agent 的分析结果。"""

    agent_name: str  # "AssessmentAgent" / "TutorAgent" / "HintAgent"
    role: str  # "学情评估" / "教学引导" / "提示建议"
    content: str  # 该 Agent 的输出内容
    priority: int = 1  # 1=必须包含, 2=条件包含, 3=可选


class SynthesisInput(BaseModel):
    """合成器的输入——来自多个 Agent 的输出集合。"""

    learner_id: str
    problem_context: str = ""  # 题目背景
    conversation_history: str = ""  # 最近的对话
    agent_outputs: list[AgentInput] = Field(default_factory=list)
    mode: str = "guide"  # "guide" / "hint" / "praise" / "reveal"


class SynthesizerAgent:
    """ITAS 风格的合成器 Agent。

    不订阅 EventBus，通过 orchestrator 直接调用。
    设计为"纯函数"式——输入多 Agent 输出，输出一段自然文本。
    """

    def __init__(self, prompt_library=None) -> None:
        self._prompt_library = prompt_library

    async def synthesize(self, synth_input: SynthesisInput) -> str:
        """融合多个 Agent 的输出为一段自然对话。"""

        # 1. 先检查安全边界——绝对不直接给答案
        safety_check = self._safety_filter(synth_input)
        if safety_check:
            logger.warning("[Synthesizer] Safety filter triggered: %s", safety_check)
            # 不改内容，但在末尾加引导
            return safety_check

        # 2. 构建 LLM prompt
        prompt = self._build_prompt(synth_input)

        # 3. 调用 LLM 合成
        return await self._llm_synthesize(prompt)

    def _safety_filter(self, synth_input: SynthesisInput) -> str | None:
        """安全边界：检查是否有 Agent 输出了完整答案。

        如果 evaluate 模式包含了解题步骤，拦截并改为引导。
        返回 None 表示通过，返回字符串表示拦截后的替代回复。
        """
        for output in synth_input.agent_outputs:
            content = output.content.lower()
            # 检测危险模式
            dangerous_patterns = [
                "答案是", "答案为", "正确答案是", "结果是",
                "步骤1", "步骤一", "第一步", "解：",
                "answer is", "solution:",
            ]
            for pattern in dangerous_patterns:
                if pattern in content:
                    return (
                        "我注意到你可能在找答案。让我换一种方式引导你思考："
                        "回想一下我们刚才讨论的关键概念，你能从那个角度再试试吗？"
                    )
        return None

    def _build_prompt(self, synth_input: SynthesisInput) -> str:
        """构建合成 prompt——按 ITAS 的三段式结构。"""
        parts = ["请根据以下分析，生成一段自然的导师回复：\n"]

        # 按优先级排序
        sorted_outputs = sorted(synth_input.agent_outputs, key=lambda x: x.priority)

        for output in sorted_outputs:
            parts.append(f"【{output.role}】来自 {output.agent_name}：")
            parts.append(output.content)
            parts.append("")

        if synth_input.problem_context:
            parts.insert(1, f"**题目背景**：{synth_input.problem_context}\n")

        if synth_input.conversation_history:
            parts.insert(2, f"**对话历史**：\n{synth_input.conversation_history}\n")

        # 模式指示
        mode_instructions = {
            "guide": "学生答对了或接近正确，以鼓励+下一个引导问题为主线",
            "hint": "学生卡住了，以自然嵌入提示为主线，不要暴露提示级别",
            "praise": "学生完成了阶段性目标，以祝贺+总结为主线",
            "reveal": "学生反复尝试失败，以安慰+展示思路（不是答案）为主线",
        }
        parts.append(f"**回复模式**：{mode_instructions.get(synth_input.mode, '')}")

        return "\n".join(parts)

    async def _llm_synthesize(self, prompt: str) -> str:
        """调用 LLM 完成合成。失败则回退到基于规则的拼接。"""
        try:
            from openai import OpenAI
            from config.settings import settings

            if settings.openai_api_key:
                client = OpenAI(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                )
                response = client.chat.completions.create(
                    model=settings.openai_model,
                    messages=[
                        {"role": "system", "content": SYNTHESIZER_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    max_tokens=250,
                    timeout=15.0,
                )
                text = (response.choices[0].message.content or "").strip()
                if text:
                    return text
        except Exception as e:
            logger.warning("[Synthesizer] LLM call failed: %s", e)

        return self._fallback_synthesize(prompt)

    def _fallback_synthesize(self, prompt: str) -> str:
        """LLM 不可用时的规则拼接——保证系统永不崩溃。"""
        # 从 prompt 中提取各 agent 的输出片段
        import re
        parts = re.findall(r"【(.+?)】来自 (.+?)：\n(.+?)(?=\n【|\Z)", prompt, re.DOTALL)

        if not parts:
            return "让我们继续思考这个问题。你目前的理解到什么程度了？"

        # 简单规则：优先教学引导 > 提示建议 > 学情评估
        guide_text = ""
        hint_text = ""
        assess_text = ""

        for role, agent, content in parts:
            content = content.strip()
            if "教学引导" in role:
                guide_text = content
            elif "提示建议" in role:
                hint_text = content
            elif "学情评估" in role:
                assess_text = content

        # 按模式拼接
        if guide_text:
            result = guide_text
            if hint_text and len(result) < 100:
                result += f"\n\n💡 {hint_text}"
        elif hint_text:
            result = hint_text
        else:
            result = "让我们换个角度想一想这个问题。"

        return result

    # ── 便捷工厂方法 ──

    def build_guide_input(
        self, learner_id: str, problem: str, history: str,
        assessment_text: str, tutor_text: str,
    ) -> SynthesisInput:
        """构建「引导模式」输入——学生答对或接近时使用。"""
        return SynthesisInput(
            learner_id=learner_id,
            problem_context=problem,
            conversation_history=history,
            mode="guide",
            agent_outputs=[
                AgentInput(
                    agent_name="AssessmentAgent", role="学情评估",
                    content=assessment_text, priority=2,
                ),
                AgentInput(
                    agent_name="TutorAgent", role="教学引导",
                    content=tutor_text, priority=1,
                ),
            ],
        )

    def build_hint_input(
        self, learner_id: str, problem: str, history: str,
        assessment_text: str, tutor_text: str, hint_text: str,
        hint_level: int = 1,
    ) -> SynthesisInput:
        """构建「提示模式」输入——学生卡住时使用。"""
        return SynthesisInput(
            learner_id=learner_id,
            problem_context=problem,
            conversation_history=history,
            mode="hint",
            agent_outputs=[
                AgentInput(
                    agent_name="AssessmentAgent", role="学情评估",
                    content=assessment_text, priority=3,
                ),
                AgentInput(
                    agent_name="TutorAgent", role="教学引导",
                    content=tutor_text, priority=2,
                ),
                AgentInput(
                    agent_name="HintAgent", role="提示建议",
                    content=f"[L{hint_level}] {hint_text}", priority=1,
                ),
            ],
        )

    def build_praise_input(
        self, learner_id: str, problem: str, history: str,
        assessment_text: str, tutor_text: str,
    ) -> SynthesisInput:
        """构建「表扬模式」输入——学生完成阶段性目标时使用。"""
        return SynthesisInput(
            learner_id=learner_id,
            problem_context=problem,
            conversation_history=history,
            mode="praise",
            agent_outputs=[
                AgentInput(
                    agent_name="AssessmentAgent", role="学情评估",
                    content=assessment_text, priority=1,
                ),
                AgentInput(
                    agent_name="TutorAgent", role="教学引导",
                    content=tutor_text, priority=2,
                ),
            ],
        )
