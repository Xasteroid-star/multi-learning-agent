"""PhotoTutorAgent 测试。"""

import pytest
from core.event_bus import EventBus, Event, EventType
from agents.photo_tutor_agent import PhotoTutorAgent


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
