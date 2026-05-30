from core.ocr_engine import recognize_math_from_photo
from core.problem_analyzer import analyze_problem, ProblemAnalysis, SolutionStep
import asyncio, traceback

async def test():
    # 1. OCR
    print("1. OCR engine...", end=" ", flush=True)
    try:
        r = await recognize_math_from_photo(b"test")
        print(f"OK: {r.problem_text[:60]}")
    except Exception as e:
        print(f"FAIL: {e}")
        traceback.print_exc()

    # 2. Problem Analyzer
    print("2. Problem Analyzer...", end=" ", flush=True)
    try:
        r = await analyze_problem("二次函数 f(x)=x^2+2x-3 求顶点", {"grade":"初三","weak_topics":[]})
        print(f"OK: kp={r.knowledge_points}, steps={len(r.solution_steps)}")
    except Exception as e:
        print(f"FAIL: {e}")
        traceback.print_exc()

    # 3. Orchestrator
    print("3. Orchestrator...", end=" ", flush=True)
    try:
        from api.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        analysis = ProblemAnalysis(
            problem_text="test", knowledge_points=["test"], difficulty=1,
            solution_steps=[SolutionStep(step_number=1, description="t", key_insight="t", socratic_prompt="t?")],
        )
        sid = orch.create_photo_session("u1", analysis)
        print(f"OK: {sid}")
    except Exception as e:
        print(f"FAIL: {e}")
        traceback.print_exc()

    # 4. route handler import check
    print("4. Route imports...", end=" ", flush=True)
    from api.main import app
    from core.ocr_engine import OCRResult
    print("OK")

asyncio.run(test())
