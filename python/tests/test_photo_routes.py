"""Photo Routes 测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from api.main import app
from core.problem_analyzer import ProblemAnalysis, SolutionStep


@pytest.fixture
def test_app():
    # 设置 mock orchestrator，避免 lifespan 初始化问题
    mock_orch = MagicMock()
    mock_orch.create_photo_session.return_value = "ps_test_001"
    mock_orch.get_learner_progress.return_value = {
        "knowledge_points": {},
        "total_questions": 0,
        "correct_rate": 0.0,
    }

    # Setup mock photo session for GET /photo-session/{id}
    mock_session = MagicMock()
    mock_session.session_id = "ps_test_001"
    mock_session.learner_id = "u1"
    mock_session.state = MagicMock(value="guiding")
    mock_session.problem_analysis = None
    mock_session.conversation_history = []
    mock_session.current_step = 1
    mock_session.solution_steps = []
    mock_session.hint_count = 0
    mock_session.created_at = "2024-01-01T00:00:00"
    mock_session.last_activity = "2024-01-01T00:01:00"
    mock_orch.photo_tutor.session_manager.get_session.return_value = mock_session

    app.state.orchestrator = mock_orch
    return app


@pytest.mark.asyncio
async def test_photo_solve_endpoint_returns_session(test_app):
    """POST /api/v1/photo-solve 应返回 session_id + first_guidance"""
    mock_analysis = ProblemAnalysis(
        problem_text="求 f(x)=x²+2x-3 的顶点坐标",
        knowledge_points=["二次函数"],
        difficulty=2,
        solution_steps=[
            SolutionStep(step_number=1, description="识别函数", key_insight="标准式",
                         socratic_prompt="这是什么函数？"),
        ],
        relevance_to_weak=0.5,
    )

    mock_ocr_result = MagicMock()
    mock_ocr_result.problem_text = "求 f(x)=x²+2x-3 的顶点坐标"
    mock_ocr_result.has_math_formula = True
    mock_ocr_result.confidence = 0.9

    with patch("core.ocr_engine.recognize_math_from_photo", new_callable=AsyncMock) as mock_ocr, \
         patch("core.problem_analyzer.analyze_problem", new_callable=AsyncMock) as mock_analyze:

        mock_ocr.return_value = mock_ocr_result
        mock_analyze.return_value = mock_analysis

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/photo-solve",
                files={"image": ("test.jpg", b"fake_image", "image/jpeg")},
                data={"learner_id": "u1"},
            )

    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["session_id"].startswith("ps_")
    assert "problem_text" in data
    assert "knowledge_points" in data
    assert "first_guidance" in data


@pytest.mark.asyncio
async def test_photo_solve_rejects_non_image(test_app):
    """POST /api/v1/photo-solve 应拒绝非图片文件"""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/photo-solve",
            files={"image": ("test.txt", b"not an image", "text/plain")},
            data={"learner_id": "u1"},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_photo_solve_missing_learner_id(test_app):
    """POST /api/v1/photo-solve 缺少 learner_id 返回 422"""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/photo-solve",
            files={"image": ("test.jpg", b"fake", "image/jpeg")},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_photo_reply_returns_next_action(test_app):
    """POST /api/v1/photo-session/{id}/reply 应返回下一步操作"""
    mock_analysis = ProblemAnalysis(
        problem_text="求 f(x)=x²+2x-3 的顶点坐标",
        knowledge_points=["二次函数"],
        difficulty=2,
        solution_steps=[
            SolutionStep(step_number=1, description="识别函数", key_insight="标准式 二次函数",
                         socratic_prompt="这是什么函数？"),
            SolutionStep(step_number=2, description="求顶点", key_insight="顶点公式 x=-b/(2a)",
                         socratic_prompt="顶点公式是什么？"),
        ],
        relevance_to_weak=0.5,
    )

    orch = test_app.state.orchestrator
    orch.submit_photo_reply.return_value = {
        "action": "praise",
        "message": "✅ 正确！顶点公式是什么？",
        "session_state": "guiding",
    }
    session_id = orch.create_photo_session("u1", mock_analysis)
    from core.photo_session import SessionState
    orch.photo_tutor.session_manager.get_session(session_id).state = SessionState.GUIDING

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/photo-session/{session_id}/reply",
            json={"learner_id": "u1", "reply": "这是二次函数，标准形式是 f(x)=ax²+bx+c"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] in ("praise", "follow_up", "hint", "reveal", "summarize")
    assert "message" in data
    assert "session_state" in data


@pytest.mark.asyncio
async def test_photo_reply_nonexistent_session(test_app):
    """回复不存在的会话返回 404"""
    test_app.state.orchestrator.submit_photo_reply.return_value = None
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/photo-session/nonexistent/reply",
            json={"learner_id": "u1", "reply": "hello"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_photo_session(test_app):
    """GET /api/v1/photo-session/{id} 应返回会话状态"""
    mock_analysis = ProblemAnalysis(
        problem_text="求顶点",
        knowledge_points=["二次函数"],
        difficulty=2,
        solution_steps=[
            SolutionStep(step_number=1, description="识别", key_insight="标准式", socratic_prompt="这是什么？"),
        ],
    )
    orch = test_app.state.orchestrator
    session_id = orch.create_photo_session("u1", mock_analysis)

    # Configure the mock session that the endpoint will return
    mock_session = orch.photo_tutor.session_manager.get_session(session_id)
    mock_session.problem_analysis = mock_analysis
    mock_session.solution_steps = mock_analysis.solution_steps
    mock_session.current_step = 1

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/photo-session/{session_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == session_id
    assert data["problem_text"] == "求顶点"
    assert "conversation_history" in data
    assert "state" in data


@pytest.mark.asyncio
async def test_get_profile(test_app):
    """GET /api/v1/profile/{learner_id} 应返回学生画像"""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/api/v1/profile/u1")

    assert response.status_code == 200
    data = response.json()
    assert data["learner_id"] == "u1"
    assert "progress" in data
