"""
温度感报告生成器 — 将冷冰冰的数据转化为家长会感动的成长报告。

核心理念：
- 每个数据点背后是一个真实的孩子
- 报告要有「具体行为」而非「笼统评价」
- 语气温暖但不肉麻，专业但不冰冷
- LLM 不可用时自动回退到规则模板

JD 对应：JD 第二条「面向家长和学员输出温度感与专业度兼具的成长内容」
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.five_forces_model import (
    FiveForcesProfile, ForceDimension, FORCE_LABELS, ForceObservation,
)
from core.prompt_library import PromptLibrary

logger = logging.getLogger(__name__)


class ReportSection(BaseModel):
    """报告的一个章节。"""
    title: str
    content: str
    icon: str = ""
    order: int = 0


class GrowthReport(BaseModel):
    """完整的成长报告。"""
    learner_id: str
    child_name: str
    camp_name: str
    season: str
    report_date: str = Field(default_factory=lambda: datetime.now().isoformat())
    sections: list[ReportSection] = Field(default_factory=list)
    generated_by: str = "GrowthAgent"


class ReportWriter:
    """报告生成器 — 将数据源组装为有温度的成长报告。"""

    def __init__(self, prompt_library: PromptLibrary | None = None) -> None:
        self._prompt_library = prompt_library

    async def generate_camp_report(
        self,
        child_name: str,
        learner_id: str,
        camp_name: str,
        season: str,
        age: int,
        days: int,
        five_forces: FiveForcesProfile,
        timeline=None,
        mentor_notes: list[str] | None = None,
        projects: list[dict] | None = None,
    ) -> GrowthReport:
        """生成结营成长报告。"""
        report = GrowthReport(
            learner_id=learner_id,
            child_name=child_name,
            camp_name=camp_name,
            season=season,
        )

        # Section 1: 封面语
        cover_text = await self._generate_cover(child_name, camp_name, five_forces)
        report.sections.append(ReportSection(
            title="写在前面",
            content=cover_text,
            icon="🌟",
            order=1,
        ))

        # Section 2: 五力成长图
        for dim in ForceDimension:
            score = five_forces.get_score(dim)
            level = five_forces.get_level(dim)
            labels = FORCE_LABELS[dim]
            dim_events = five_forces.get_dimension_growth(dim)
            dim_timeline_events = timeline.get_dimension_growth(dim.value) if timeline else []

            desc = self._format_dimension_section(
                child_name, labels, score, level,
                dim_events, dim_timeline_events,
            )
            report.sections.append(ReportSection(
                title=labels["name"],
                content=desc,
                icon=labels["icon"],
                order=2,
            ))

        # Section 3: 高光时刻
        highlights = five_forces.get_highlight_observations(limit=3)
        highlight_text = self._format_highlights(child_name, highlights, projects)
        report.sections.append(ReportSection(
            title="高光时刻",
            content=highlight_text,
            icon="✨",
            order=3,
        ))

        # Section 4: 成长建议
        suggestions = self._generate_suggestions(child_name, five_forces)
        report.sections.append(ReportSection(
            title="继续成长的建议",
            content=suggestions,
            icon="🌱",
            order=4,
        ))

        # Section 5: 导师寄语
        if mentor_notes:
            mentor_text = self._format_mentor_message(child_name, mentor_notes)
            report.sections.append(ReportSection(
                title="导师想对你说",
                content=mentor_text,
                icon="💌",
                order=5,
            ))

        return report

    async def _generate_cover(
        self, child_name: str, camp_name: str, forces: FiveForcesProfile,
    ) -> str:
        """生成封面语。尝试用 LLM，失败则用规则模板。"""
        scores = forces.get_radar_data()
        top_dim = max(scores, key=scores.get)
        top_label = FORCE_LABELS[ForceDimension(top_dim)]

        # 尝试 LLM
        if self._prompt_library:
            try:
                result = self._prompt_library.render(
                    "report.growth_report",
                    child_name=child_name,
                    season="夏季",
                    age="10",
                    days="7",
                    camp_name=camp_name,
                    force_scores=str(scores),
                    key_events="",
                    mentor_notes="",
                    projects="",
                )
                if result:
                    from openai import OpenAI
                    from config.settings import settings

                    if settings.openai_api_key:
                        client = OpenAI(
                            api_key=settings.openai_api_key,
                            base_url=settings.openai_base_url,
                        )
                        # 只请求封面语部分
                        system, user = result
                        user += "\n\n请只写【封面语】部分，80字左右，温暖有感染力。不要输出标题。"
                        response = client.chat.completions.create(
                            model=settings.openai_model,
                            messages=[
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ],
                            temperature=0.8,
                            max_tokens=200,
                            timeout=15.0,
                        )
                        text = (response.choices[0].message.content or "").strip()
                        # 清理 LLM 可能输出的标题格式
                        for prefix in ["**【封面语】**", "【封面语】", "## 封面语", "# 封面语"]:
                            text = text.replace(prefix, "").strip()
                        if text:
                            return text
            except Exception as e:
                logger.warning("LLM cover generation failed: %s", e)

        # 回退规则模板
        return (
            f"亲爱的{child_name}家长：\n\n"
            f"在{camp_name}的这段时光里，我们看到了一个不断探索、勇敢尝试的{child_name}。"
            f"从第一天的新奇与些许不安，到最后一天的自信与不舍，"
            f"每一天都在书写着属于自己的成长故事。\n\n"
            f"特别是在{top_label['name']}方面，{child_name}展现出了令人惊喜的变化。"
            f"以下是孩子在营期间的成长记录，希望这些文字能让你看到那些闪闪发光的瞬间。"
        )

    def _format_dimension_section(
        self, child_name: str, labels: dict, score: float, level: str,
        obs_events: list[dict], timeline_events: list[dict],
    ) -> str:
        """格式化单个五力维度的报告段落。"""
        bar_length = 10
        filled = int(score / 100 * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)

        lines = [
            f"**得分**: {score:.0f}/100 | **阶段**: {level}",
            f"`{bar}`",
            "",
        ]

        # 温度描述
        if score < 30:
            lines.append(
                f"在这个维度上，{child_name}正在迈出探索的第一步。"
                f"每一次小小的尝试都是珍贵的开始。"
            )
        elif score < 55:
            lines.append(
                f"{child_name}在{labels['name']}方面正在稳步成长，"
                f"已经开始展现出自己的特点和风格。"
            )
        elif score < 75:
            lines.append(
                f"{child_name}的{labels['name']}已经发展得相当出色，"
                f"在营地的日常中经常让我们眼前一亮。"
            )
        else:
            lines.append(
                f"这是{child_name}特别闪光的领域！在营地中展现出的"
                f"{labels['name']}让导师和其他孩子都深受感染。"
            )

        # 具体观察引用
        if obs_events:
            latest = obs_events[-1]
            lines.append(f"\n> 比如：{latest['evidence']}")
        elif timeline_events:
            first = timeline_events[0]
            lines.append(f"\n> 比如：{first['description']}")

        return "\n".join(lines)

    def _format_highlights(
        self, child_name: str, observations: list[ForceObservation],
        projects: list[dict] | None,
    ) -> str:
        """格式化高光时刻章节。"""
        if not observations and not projects:
            return (
                f"{child_name}在营地的每一天都在悄悄成长，"
                f"那些看似平常的瞬间，其实都是成长的印记。"
            )

        lines = []
        for obs in observations:
            labels = FORCE_LABELS[obs.dimension]
            context_str = f"在{obs.context}中，" if obs.context else ""
            lines.append(
                f"**{labels['icon']} {labels['name']}** — "
                f"{context_str}{obs.evidence}"
            )
            lines.append("")

        if projects:
            lines.append("**作品/项目**:")
            for proj in projects:
                lines.append(f"- **{proj.get('name', '')}**：{proj.get('description', '')}")

        return "\n".join(lines)

    def _generate_suggestions(self, child_name: str, forces: FiveForcesProfile) -> str:
        """根据五力画像生成成长建议。"""
        scores = forces.get_radar_data()
        weakest_dim = min(scores, key=scores.get)
        labels = FORCE_LABELS[ForceDimension(weakest_dim)]

        dim_suggestions = {
            "curiosity": "多问「你觉得呢？」而不是直接给答案。鼓励孩子提出问题，"
                         "比回答问题更重要。带孩子去陌生的环境，让 ta 的好奇心自然生长。",
            "creativity": "提供开放式的材料和任务，少一些「应该怎么做」，多一些「你想怎么做」。"
                          "珍视孩子那些「不标准」的想法，它们是创造力的种子。",
            "collaboration": "创造需要合作才能完成的家庭任务，让孩子体验「一起做到」的快乐。"
                             "当孩子与他人发生冲突时，引导 ta 理解对方的感受。",
            "resilience": "当孩子遇到挫折时，先共情再引导。"
                          "让 ta 知道「失败是成长的一部分」，而非「失败就是我不够好」。"
                          "分享你自己克服困难的经历，孩子会从中获得力量。",
            "communication": "每天留出固定的「分享时间」，认真听孩子讲 ta 的故事，"
                             "不打断、不评判。用追问帮助 ta 把想法说得更完整、更生动。",
        }

        suggestions = [
            f"**当前成长空间最大的维度是{labels['name']}**，建议在日常生活中：",
            f"{dim_suggestions.get(weakest_dim, '继续加油！')}",
            "",
            "**其他维度的日常练习：**",
        ]

        for dim_key, suggestion in dim_suggestions.items():
            if dim_key != weakest_dim:
                force_labels = FORCE_LABELS[ForceDimension(dim_key)]
                suggestions.append(
                    f"- **{force_labels['name']}**：{suggestion}"
                )

        return "\n".join(suggestions)

    def _format_mentor_message(
        self, child_name: str, notes: list[str],
    ) -> str:
        """格式化导师寄语。"""
        combined = "。".join(notes[:3])
        return (
            f"亲爱的{child_name}：\n\n"
            f"在营地的每一天，我们都看到了一个独一无二的你。{combined}。\n\n"
            f"希望你带着这份勇气和好奇心，继续探索这个广阔而有趣的世界。"
            f"我们相信，你的未来有无限可能。\n\n"
            f"— 营地导师团队"
        )

    def export_markdown(self, report: GrowthReport) -> str:
        """将报告导出为 Markdown 格式。"""
        lines = [
            f"# {report.child_name}的成长报告",
            "",
            f"**{report.camp_name}** | {report.season} | {report.report_date[:10]}",
            "",
            "---",
            "",
        ]

        for section in sorted(report.sections, key=lambda s: s.order):
            lines.append(f"## {section.icon} {section.title}")
            lines.append("")
            lines.append(section.content)
            lines.append("")

        return "\n".join(lines)
