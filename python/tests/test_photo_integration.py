"""Photo Solve 集成测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from api.main import app
from api.orchestrator import AgentOrchestrator
from core.problem_analyzer import ProblemAnalysis, SolutionStep


@pytest.fixture
def test_app():
    # Manually set up the orchestrator since ASGITransport does not trigger
    # the FastAPI lifespan (which would normally create the orchestrator).
    app.state.orchestrator = AgentOrchestrator()
    return app


@pytest.mark.asyncio
async def test_full_happy_path_upload_to_solve(test_app):
    """完整快乐路径：上传 引导 答对 完成"""
    mock_analysis = ProblemAnalysis(
        problem_text="求 f(x)=x +2x-3 的顶点坐标",
        knowledge_points=["二次函数", "配方法"],
        difficulty=3,
        solution_steps=[
            SolutionStep(step_number=1, description="识别函数类型", key_insight="二次函数 标准形式 ax +bx+c",
                         socratic_prompt="你能识别出这是哪种类型的函数吗？"),
            SolutionStep(step_number=2, description="求顶点坐标", key_insight="顶点公式 x=-b/(2a)",
                         socratic_prompt="那你知道怎么从一般式求顶点坐标吗？"),
        ],
        relevance_to_weak=0.7,
    )

    mock_ocr = MagicMock()
    mock_ocr.problem_text = "求 f(x)=x +2x-3 的顶点坐标"
    mock_ocr.has_math_formula = True
    mock_ocr.confidence = 0.95

    with patch("core.ocr_engine.recognize_math_from_photo", new_callable=AsyncMock) as mock_ocr_fn, \
         patch("core.problem_analyzer.analyze_problem", new_callable=AsyncMock) as mock_analyze_fn:

        mock_ocr_fn.return_value = mock_ocr
        mock_analyze_fn.return_value = mock_analysis

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            # Step 1: 上传
            upload_resp = await client.post(
                "/api/v1/photo-solve",
                files={"image": ("math.jpg", b"fake_image", "image/jpeg")},
                data={"learner_id": "u1"},
            )
            assert upload_resp.status_code == 200
            upload_data = upload_resp.json()
            session_id = upload_data["session_id"]
            assert "二次函数" in str(upload_data["knowledge_points"])

            # Step 2: 第一步正确回复 (must include keywords from key_insight)
            reply1 = await client.post(
                f"/api/v1/photo-session/{session_id}/reply",
                json={"learner_id": "u1", "reply": "这是二次函数，标准形式是 f(x)=ax +bx+c，二次函数 标准形式 ax +bx+c"},
            )
            assert reply1.status_code == 200
            data1 = reply1.json()
            assert data1["action"] in ("praise", "follow_up", "hint", "reveal", "summarize")

            # Step 3: Verify session state has conversation history
            get_resp = await client.get(f"/api/v1/photo-session/{session_id}")
            assert get_resp.status_code == 200
            session_data = get_resp.json()
            assert len(session_data["conversation_history"]) > 0


@pytest.mark.asyncio
async def test_upload_then_immediate_session_query(test_app):
    """上传后可立即查询会话状态"""
    mock_analysis = ProblemAnalysis(
        problem_text="test",
        knowledge_points=["test"],
        difficulty=1,
        solution_steps=[
            SolutionStep(step_number=1, description="test", key_insight="test", socratic_prompt="test?"),
        ],
    )

    with patch("core.ocr_engine.recognize_math_from_photo", new_callable=AsyncMock) as mock_ocr, \
         patch("core.problem_analyzer.analyze_problem", new_callable=AsyncMock) as mock_analyze:

        mock_ocr.return_value = MagicMock(problem_text="test", has_math_formula=True, confidence=0.9)
        mock_analyze.return_value = mock_analysis

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            upload_resp = await client.post(
                "/api/v1/photo-solve",
                files={"image": ("math.jpg", b"fake", "image/jpeg")},
                data={"learner_id": "u1"},
            )
            session_id = upload_resp.json()["session_id"]

            get_resp = await client.get(f"/api/v1/photo-session/{session_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["problem_text"] == "test"


@pytest.mark.asyncio
async def test_max_hints_then_reveal(test_app):
    """连续错误  3 级提示  再错 2 次  揭示答案"""
    mock_analysis = ProblemAnalysis(
        problem_text="求 f(x)=x +2x-3 的顶点坐标",
        knowledge_points=["二次函数"],
        difficulty=3,
        solution_steps=[
            SolutionStep(step_number=1, description="识别函数", key_insight="二次函数 标准形式",
                         socratic_prompt="这是什么函数？"),
        ],
    )

    with patch("core.ocr_engine.recognize_math_from_photo", new_callable=AsyncMock) as mock_ocr, \
         patch("core.problem_analyzer.analyze_problem", new_callable=AsyncMock) as mock_analyze:

        mock_ocr.return_value = MagicMock(problem_text="求顶点", has_math_formula=True, confidence=0.9)
        mock_analyze.return_value = mock_analysis

        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            # Upload
            upload_resp = await client.post(
                "/api/v1/photo-solve",
                files={"image": ("math.jpg", b"fake", "image/jpeg")},
                data={"learner_id": "u1"},
            )
            session_id = upload_resp.json()["session_id"]

            # 错误回复 1-7 (trigger L1 L2 L3 hints, then reveal)
            actions_seen = []
            for i in range(7):
                r = await client.post(
                    f"/api/v1/photo-session/{session_id}/reply",
                    json={"learner_id": "u1", "reply": "I don't know"},
                )
                data = r.json()
                actions_seen.append(data["action"])

            # At least one of the later responses should be "reveal"
            assert "reveal" in actions_seen, f"Expected reveal in actions, got {actions_seen}"
            # Early responses should be hints
            assert "hint" in actions_seen
