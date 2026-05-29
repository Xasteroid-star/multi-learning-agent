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
