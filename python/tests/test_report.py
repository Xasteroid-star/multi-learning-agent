"""测试成长报告生成。"""
import pytest
from core.five_forces_model import (
    build_default_five_forces_profile, ForceObservation, ForceDimension,
)
from agents.growth.growth_agent import GrowthTimeline
from agents.growth.report_writer import ReportWriter


def test_report_writer_default():
    writer = ReportWriter()
    forces = build_default_five_forces_profile("test_learner")
    forces.record_observation(ForceObservation(
        dimension=ForceDimension.CURIOSITY,
        score=80.0,
        evidence="连续三天主动早起去观察鸟类",
        context="清晨观鸟活动",
    ))

    import asyncio
    report = asyncio.run(writer.generate_camp_report(
        child_name="小明",
        learner_id="test_learner",
        camp_name="自然探索营",
        season="暑假",
        age=8,
        days=7,
        five_forces=forces,
    ))

    assert report.child_name == "小明"
    assert report.camp_name == "自然探索营"
    # 至少封面语 + 5个力 + 高光时刻 + 成长建议 = 8
    assert len(report.sections) >= 7

    # 验证 Markdown 导出
    md = writer.export_markdown(report)
    assert "小明" in md
    assert "自然探索营" in md


def test_report_sections_have_content():
    writer = ReportWriter()
    forces = build_default_five_forces_profile("test_learner")

    import asyncio
    report = asyncio.run(writer.generate_camp_report(
        child_name="测试", learner_id="test",
        camp_name="测试营", season="暑假",
        age=10, days=5, five_forces=forces,
    ))

    for section in report.sections:
        assert section.title, f"Section should have title"
        assert section.content, f"Section '{section.title}' should have content"


def test_dimension_section_formatting():
    writer = ReportWriter()
    text = writer._format_dimension_section(
        "小明",
        {"name": "好奇心", "icon": "🔍"},
        score=72.0,
        level="发展期",
        obs_events=[{"evidence": "主动问了关于昆虫的深入问题"}],
        timeline_events=[],
    )
    assert "小明" in text
    assert "72" in text
    assert "发展期" in text
    assert "昆虫" in text


def test_report_with_mentor_notes():
    writer = ReportWriter()
    forces = build_default_five_forces_profile("test_learner")

    import asyncio
    report = asyncio.run(writer.generate_camp_report(
        child_name="小红", learner_id="test",
        camp_name="创意工坊营", season="寒假",
        age=12, days=7, five_forces=forces,
        mentor_notes=["小红的手工作品让我们惊喜",
                       "她在团队中越来越主动了"],
    ))

    # 检查导师寄语章节
    mentor_sections = [s for s in report.sections if s.title == "导师想对你说"]
    assert len(mentor_sections) == 1
    assert "小红" in mentor_sections[0].content


def test_report_sections_order():
    writer = ReportWriter()
    forces = build_default_five_forces_profile("test_learner")

    import asyncio
    report = asyncio.run(writer.generate_camp_report(
        child_name="测试", learner_id="test",
        camp_name="测试营", season="暑假",
        age=10, days=5, five_forces=forces,
    ))

    sorted_sections = sorted(report.sections, key=lambda s: s.order)
    # 验证顺序：封面语 -> 五力 -> 高光时刻 -> 成长建议
    assert sorted_sections[0].title == "写在前面"
    assert sorted_sections[-1].title in ("导师想对你说", "继续成长的建议")


def test_growth_timeline():
    timeline = GrowthTimeline(learner_id="test")
    assert timeline.learner_id == "test"
    assert len(timeline.events) == 0

    timeline.add_milestone("第一次独立完成挑战", "在绳索挑战中坚持到最后")
    assert len(timeline.milestones) == 1


def test_highlights_with_no_data():
    writer = ReportWriter()
    text = writer._format_highlights("小明", [], None)
    assert "小明" in text
    assert "成长" in text
