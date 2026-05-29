"""Photo Session 测试。"""

import pytest
from core.photo_session import PhotoSession, SessionState, ConversationEntry, PhotoSessionManager
from core.problem_analyzer import SolutionStep, ProblemAnalysis


def make_sample_analysis() -> ProblemAnalysis:
    return ProblemAnalysis(
        problem_text="已知 f(x)=x²+2x-3，求顶点坐标",
        knowledge_points=["二次函数", "配方法"],
        difficulty=3,
        solution_steps=[
            SolutionStep(step_number=1, description="识别函数", key_insight="标准式", socratic_prompt="这是什么函数？"),
            SolutionStep(step_number=2, description="求顶点", key_insight="顶点公式", socratic_prompt="顶点公式是什么？"),
        ],
        relevance_to_weak=0.7,
    )


def test_photo_session_creation():
    """PhotoSession 基础创建"""
    analysis = make_sample_analysis()
    session = PhotoSession(
        session_id="ps_001",
        learner_id="u1",
        problem_analysis=analysis,
    )
    assert session.session_id == "ps_001"
    assert session.learner_id == "u1"
    assert session.state == SessionState.IDLE
    assert session.current_step == 0
    assert session.hint_count == 0
    assert session.attempts_since_last_hint == 0
    assert len(session.conversation_history) == 0
    assert len(session.solution_steps) == 2


def test_photo_session_add_conversation():
    """对话历史应正确追加"""
    session = PhotoSession(
        session_id="ps_001", learner_id="u1", problem_analysis=make_sample_analysis(),
    )
    session.add_system_message("guidance", "这是什么函数？")
    session.add_student_message("这是二次函数")

    assert len(session.conversation_history) == 2
    assert session.conversation_history[0].role == "system"
    assert session.conversation_history[0].msg_type == "guidance"
    assert session.conversation_history[1].role == "student"


def test_photo_session_state_transitions():
    """状态应正确转换"""
    session = PhotoSession(
        session_id="ps_001", learner_id="u1", problem_analysis=make_sample_analysis(),
    )
    assert session.state == SessionState.IDLE

    for state in [SessionState.ANALYZING, SessionState.GUIDING, SessionState.PRAISING,
                   SessionState.HINTING, SessionState.REVEALING, SessionState.SUMMARIZING,
                   SessionState.CLOSED]:
        session.state = state
        assert session.state == state


def test_photo_session_hint_tracking():
    """提示计数应正确追踪"""
    session = PhotoSession(
        session_id="ps_001", learner_id="u1", problem_analysis=make_sample_analysis(),
    )
    session.increment_attempts_since_last_hint()
    session.increment_attempts_since_last_hint()
    session.record_hint(1)
    assert session.hint_count == 1
    assert session.attempts_since_last_hint == 0

    session.increment_attempts_since_last_hint()
    session.increment_attempts_since_last_hint()
    session.increment_attempts_since_last_hint()
    session.record_hint(2)
    assert session.hint_count == 2

    session.record_hint(3)
    session.increment_attempts_since_last_hint()
    session.increment_attempts_since_last_hint()
    assert session.should_reveal() is True


def test_photo_session_completed_steps():
    """步骤完成追踪"""
    session = PhotoSession(
        session_id="ps_001", learner_id="u1", problem_analysis=make_sample_analysis(),
    )
    assert session.all_steps_completed() is False
    session.complete_current_step()
    assert session.current_step == 1
    assert session.all_steps_completed() is False
    session.complete_current_step()
    assert session.current_step == 2
    assert session.all_steps_completed() is True


@pytest.mark.asyncio
async def test_session_manager_create_and_get():
    """创建后可获取会话"""
    mgr = PhotoSessionManager()
    session = mgr.create_session("u1", make_sample_analysis())
    assert session.session_id.startswith("ps_")
    assert session.learner_id == "u1"
    retrieved = mgr.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.session_id == session.session_id


@pytest.mark.asyncio
async def test_session_manager_get_nonexistent():
    """获取不存在的会话返回 None"""
    mgr = PhotoSessionManager()
    assert mgr.get_session("nonexistent") is None


@pytest.mark.asyncio
async def test_session_manager_max_concurrent():
    """每 learner 最多 3 个活跃会话"""
    mgr = PhotoSessionManager()
    s1 = mgr.create_session("u1", make_sample_analysis())
    s2 = mgr.create_session("u1", make_sample_analysis())
    s3 = mgr.create_session("u1", make_sample_analysis())
    with pytest.raises(ValueError, match="最多.*3.*活跃"):
        mgr.create_session("u1", make_sample_analysis())
    mgr.close_session(s1.session_id)
    s4 = mgr.create_session("u1", make_sample_analysis())
    assert s4.session_id != s1.session_id


@pytest.mark.asyncio
async def test_session_manager_close_session():
    """关闭后 get 返回 None"""
    mgr = PhotoSessionManager()
    session = mgr.create_session("u1", make_sample_analysis())
    mgr.close_session(session.session_id)
    assert mgr.get_session(session.session_id) is None


@pytest.mark.asyncio
async def test_session_manager_cleanup_expired():
    """过期会话（>30 min）应被清理"""
    from datetime import datetime, timedelta
    mgr = PhotoSessionManager()
    session = mgr.create_session("u1", make_sample_analysis())
    session.last_activity = (datetime.now() - timedelta(minutes=31)).isoformat()
    mgr.cleanup_expired()
    assert mgr.get_session(session.session_id) is None


@pytest.mark.asyncio
async def test_session_manager_count_active():
    """活跃会话计数正确"""
    mgr = PhotoSessionManager()
    assert mgr.count_active("u1") == 0
    s1 = mgr.create_session("u1", make_sample_analysis())
    assert mgr.count_active("u1") == 1
    s2 = mgr.create_session("u1", make_sample_analysis())
    assert mgr.count_active("u1") == 2
    mgr.close_session(s1.session_id)
    assert mgr.count_active("u1") == 1
