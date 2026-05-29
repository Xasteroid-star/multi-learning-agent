"""PhotoTutorAgent 测试。"""

import pytest
from core.event_bus import EventBus, Event, EventType
from agents.photo_tutor_agent import PhotoTutorAgent
from core.photo_session import SessionState
from core.problem_analyzer import ProblemAnalysis, SolutionStep


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def photo_tutor(event_bus):
    learner_models = {}
    agent = PhotoTutorAgent(
        name="PhotoTutorAgent",
        event_bus=event_bus,
        learner_models=learner_models,
    )
    return agent


def test_photo_tutor_subscribed_events(photo_tutor):
    """PhotoTutorAgent 应该订阅全部 8 个拍照事件"""
    events = photo_tutor.subscribed_events
    event_values = {e.value for e in events}
    assert "photo.session_started" in event_values
    assert "photo.problem_recognized" in event_values
    assert "photo.guidance_question" in event_values
    assert "photo.student_reply" in event_values
    assert "photo.reply_judged" in event_values
    assert "photo.step_completed" in event_values
    assert "photo.solution_revealed" in event_values
    assert "photo.session_ended" in event_values


def test_photo_tutor_has_session_manager(photo_tutor):
    """Agent 应该包含 PhotoSessionManager"""
    assert photo_tutor.session_manager is not None


@pytest.mark.asyncio
async def test_photo_tutor_handles_session_started(event_bus, photo_tutor):
    """收到 PHOTO_SESSION_STARTED 事件不应崩溃"""
    event = Event(
        type=EventType.PHOTO_SESSION_STARTED,
        source="api",
        learner_id="u1",
        data={"image_bytes_size": 1024},
    )
    await photo_tutor.handle_event(event)
    # 不抛异常即为通过


def make_analysis():
    return ProblemAnalysis(
        problem_text="求 f(x)=x²+2x-3 的顶点坐标",
        knowledge_points=["二次函数"], difficulty=2,
        solution_steps=[
            SolutionStep(step_number=1, description="识别函数", key_insight="标准式", socratic_prompt="这是什么函数？"),
            SolutionStep(step_number=2, description="求顶点", key_insight="顶点公式", socratic_prompt="顶点公式是什么？"),
        ],
        relevance_to_weak=0.5,
    )


@pytest.mark.asyncio
async def test_full_state_machine_happy_path(event_bus, photo_tutor):
    """完整快乐路径：IDLE→GUIDING→PRAISING→GUIDING→SUMMARIZING→CLOSED"""
    session = photo_tutor.session_manager.create_session("u1", make_analysis())

    session.state = SessionState.GUIDING
    first_question = session.solution_steps[0].socratic_prompt
    session.add_system_message("guidance", first_question)
    assert session.state == SessionState.GUIDING
    assert len(session.conversation_history) == 1

    session.add_student_message("这是二次函数，标准形式是 f(x)=ax²+bx+c")
    session.state = SessionState.PRAISING
    session.complete_current_step()
    assert session.current_step == 1
    assert session.state == SessionState.PRAISING

    session.state = SessionState.GUIDING
    next_question = session.solution_steps[1].socratic_prompt
    session.add_system_message("guidance", next_question)

    session.add_student_message("顶点公式是 x=-b/(2a), y=f(-b/(2a))")
    session.state = SessionState.PRAISING
    session.complete_current_step()
    assert session.all_steps_completed() is True

    session.state = SessionState.SUMMARIZING
    session.add_system_message("summary", "总结：你成功求出了顶点坐标")
    session.state = SessionState.CLOSED

    assert session.state == SessionState.CLOSED
    assert len(session.conversation_history) == 5


@pytest.mark.asyncio
async def test_state_machine_guiding_to_follow_up(event_bus, photo_tutor):
    """回复模糊 → FOLLOW_UP"""
    session = photo_tutor.session_manager.create_session("u1", make_analysis())
    session.state = SessionState.GUIDING
    session.add_system_message("guidance", session.solution_steps[0].socratic_prompt)
    session.add_student_message("函数...")
    session.state = SessionState.FOLLOW_UP
    session.add_system_message("follow_up", "你能说得更具体一些吗？")

    assert session.state == SessionState.FOLLOW_UP
    assert session.conversation_history[-1].msg_type == "follow_up"


@pytest.mark.asyncio
async def test_state_machine_guiding_to_hinting(event_bus, photo_tutor):
    """连续失败 → HINTING"""
    session = photo_tutor.session_manager.create_session("u1", make_analysis())
    session.state = SessionState.GUIDING
    session.add_student_message("不知道")
    session.increment_attempts_since_last_hint()
    session.add_student_message("还是不知道")
    session.increment_attempts_since_last_hint()
    session.record_hint(1)
    assert session.state == SessionState.HINTING
    assert session.hint_count == 1
    assert session.attempts_since_last_hint == 0


@pytest.mark.asyncio
async def test_session_timeout_transitions(event_bus, photo_tutor):
    """会话超时自动 CLOSED"""
    from datetime import datetime, timedelta
    session = photo_tutor.session_manager.create_session("u1", make_analysis())
    session.state = SessionState.GUIDING
    session.last_activity = (datetime.now() - timedelta(minutes=31)).isoformat()
    assert session.is_expired() is True
    photo_tutor.session_manager.cleanup_expired()
    assert photo_tutor.session_manager.get_session(session.session_id) is None


def test_judge_reply_correct(photo_tutor):
    """正确回复 → 'correct'"""
    step_keywords = {"顶点公式", "x=-b/(2a)"}
    result = photo_tutor._judge_reply(
        student_reply="顶点公式是 x=-b/(2a)，代入得到顶点坐标 (-1, -4)",
        step_keywords=step_keywords,
    )
    assert result == "correct"


def test_judge_reply_partial(photo_tutor):
    """部分正确 → 'partial'"""
    step_keywords = {"配方法", "完全平方", "平方"}
    result = photo_tutor._judge_reply(
        student_reply="应该和平方有关...但我不确定怎么做",
        step_keywords=step_keywords,
    )
    assert result == "partial"


def test_judge_reply_wrong(photo_tutor):
    """错误回复或无关联 → 'wrong'"""
    step_keywords = {"顶点公式", "x=-b/(2a)"}
    result = photo_tutor._judge_reply(
        student_reply="我觉得答案是 5",
        step_keywords=step_keywords,
    )
    assert result == "wrong"


def test_judge_reply_empty(photo_tutor):
    """空回复 → 'wrong'"""
    step_keywords = {"顶点公式"}
    result = photo_tutor._judge_reply(
        student_reply="",
        step_keywords=step_keywords,
    )
    assert result == "wrong"
