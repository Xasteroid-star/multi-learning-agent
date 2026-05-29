"""Student Profile 测试。"""

import pytest
from core.student_profile import StudentProfile


def test_student_profile_creation():
    """StudentProfile 应能正确创建"""
    profile = StudentProfile(
        learner_id="u1",
        name="小明",
        grade="初三",
        learning_style="visual",
        preferred_pace="normal",
        total_sessions=10,
        total_photo_solves=3,
        weak_topics=["二次函数", "配方法"],
        strong_topics=["有理数", "一元一次方程"],
    )
    assert profile.learner_id == "u1"
    assert profile.name == "小明"
    assert profile.grade == "初三"
    assert profile.learning_style == "visual"
    assert profile.preferred_pace == "normal"
    assert profile.total_sessions == 10
    assert profile.total_photo_solves == 3
    assert len(profile.weak_topics) == 2
    assert len(profile.strong_topics) == 2


def test_student_profile_defaults():
    """默认值检查"""
    profile = StudentProfile(
        learner_id="u2",
        name="小红",
        grade="高一",
    )
    assert profile.learning_style == "mixed"
    assert profile.preferred_pace == "normal"
    assert profile.total_sessions == 0
    assert profile.total_photo_solves == 0
    assert profile.weak_topics == []
    assert profile.strong_topics == []
    assert profile.recent_activity == []


def test_student_profile_serialization():
    """序列化为 dict 后能还原"""
    profile = StudentProfile(
        learner_id="u1",
        name="小明",
        grade="初三",
        total_sessions=5,
        weak_topics=["圆"],
    )
    data = profile.model_dump()
    restored = StudentProfile(**data)
    assert restored.learner_id == profile.learner_id
    assert restored.weak_topics == profile.weak_topics
