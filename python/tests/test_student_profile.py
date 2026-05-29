"""Student Profile 测试。"""

import os
import tempfile

import pytest
from core.student_profile import ProfileStore, StudentProfile


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


@pytest.fixture
def temp_db():
    """创建临时 SQLite 数据库"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.mark.asyncio
async def test_profile_save_and_load(temp_db):
    """保存后应能正确加载"""
    store = ProfileStore(temp_db)
    await store.init_db()

    profile = StudentProfile(
        learner_id="u1", name="小明", grade="初三", learning_style="visual",
        total_sessions=3, total_photo_solves=1, weak_topics=["配方法"],
    )
    await store.save(profile)

    loaded = await store.load("u1")
    assert loaded is not None
    assert loaded.name == "小明"
    assert loaded.grade == "初三"
    assert loaded.learning_style == "visual"
    assert loaded.total_photo_solves == 1
    assert loaded.weak_topics == ["配方法"]


@pytest.mark.asyncio
async def test_profile_load_nonexistent(temp_db):
    """加载不存在的 profile 返回 None"""
    store = ProfileStore(temp_db)
    await store.init_db()
    loaded = await store.load("nonexistent")
    assert loaded is None


@pytest.mark.asyncio
async def test_profile_update(temp_db):
    """更新后字段正确变更"""
    store = ProfileStore(temp_db)
    await store.init_db()

    profile = StudentProfile(learner_id="u1", name="小明", grade="初三")
    await store.save(profile)

    profile.total_photo_solves += 1
    profile.weak_topics.append("二次函数")
    profile.updated_at = "2026-05-29T12:00:00"
    await store.save(profile)

    loaded = await store.load("u1")
    assert loaded.total_photo_solves == 1
    assert "二次函数" in loaded.weak_topics
    assert loaded.updated_at == "2026-05-29T12:00:00"


@pytest.mark.asyncio
async def test_profile_upsert(temp_db):
    """重复 save 不会创建重复记录"""
    store = ProfileStore(temp_db)
    await store.init_db()
    await store.save(StudentProfile(learner_id="u1", name="小明", grade="初三"))
    await store.save(StudentProfile(learner_id="u1", name="小明", grade="高一"))
    loaded = await store.load("u1")
    assert loaded.grade == "高一"


@pytest.mark.asyncio
async def test_profile_refresh_weak_topics_from_bkt(temp_db):
    """从 LearnerModel 刷新 weak_topics 和 strong_topics"""
    from core.learner_model import LearnerModel

    store = ProfileStore(temp_db)
    await store.init_db()

    profile = StudentProfile(learner_id="u1", name="小明", grade="初三")
    await store.save(profile)

    model = LearnerModel("u1")
    model.update_mastery("有理数", True)
    model.update_mastery("有理数", True)
    model.update_mastery("有理数", True)
    model.update_mastery("有理数", True)
    model.update_mastery("有理数", True)
    model.update_mastery("二次函数", False)
    model.update_mastery("二次函数", False)
    model.update_mastery("二次函数", False)

    updated = await store.refresh_from_bkt(profile, model)
    assert "二次函数" in updated.weak_topics
    assert "有理数" in updated.strong_topics
