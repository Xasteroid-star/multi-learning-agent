"""REST API 路由。"""

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

router = APIRouter(tags=["education"])


class SubmitAnswerRequest(BaseModel):
    learner_id: str
    knowledge_id: str
    is_correct: bool
    time_spent_seconds: float = 0


class AskQuestionRequest(BaseModel):
    learner_id: str
    knowledge_id: str
    question: str


class SendMessageRequest(BaseModel):
    learner_id: str
    message: str
    knowledge_id: str = "general"


class PhotoSolveResponse(BaseModel):
    session_id: str
    problem_text: str
    knowledge_points: list[str]
    first_guidance: str


class PhotoReplyRequest(BaseModel):
    learner_id: str
    reply: str


class ProfileResponse(BaseModel):
    learner_id: str
    profile: dict | None = None
    progress: dict | None = None


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "multi-agent-education", "agents": 5}


@router.post("/submit")
async def submit_answer(req: SubmitAnswerRequest, request: Request):
    """学生提交答题结果。"""
    orch = request.app.state.orchestrator
    events = await orch.submit_answer(
        req.learner_id, req.knowledge_id, req.is_correct, req.time_spent_seconds
    )
    return {
        "status": "processed",
        "events_triggered": len(events),
        "events": [
            {"type": e.type.value, "source": e.source, "data": e.data}
            for e in events[-10:]
        ],
    }


@router.post("/question")
async def ask_question(req: AskQuestionRequest, request: Request):
    """学生提问。"""
    orch = request.app.state.orchestrator
    events = await orch.ask_question(req.learner_id, req.knowledge_id, req.question)
    return {
        "status": "processed",
        "events_triggered": len(events),
        "events": [
            {"type": e.type.value, "source": e.source, "data": e.data}
            for e in events[-10:]
        ],
    }


@router.post("/message")
async def send_message(req: SendMessageRequest, request: Request):
    """学生发送消息（对话）。"""
    orch = request.app.state.orchestrator
    events = await orch.send_message(req.learner_id, req.message, req.knowledge_id)
    return {
        "status": "processed",
        "events_triggered": len(events),
        "events": [
            {"type": e.type.value, "source": e.source, "data": e.data}
            for e in events[-10:]
        ],
    }


@router.get("/progress/{learner_id}")
async def get_progress(learner_id: str, request: Request):
    """获取学生学习进度。"""
    orch = request.app.state.orchestrator
    return orch.get_learner_progress(learner_id)


@router.get("/knowledge-graph")
async def get_knowledge_graph(request: Request):
    """获取知识图谱结构。"""
    orch = request.app.state.orchestrator
    graph = orch.curriculum.knowledge_graph
    return {
        "nodes": [
            {
                "id": n.id,
                "name": n.name,
                "difficulty": n.difficulty,
                "prerequisites": n.prerequisites,
                "tags": n.tags,
            }
            for n in graph.nodes.values()
        ],
        "learning_order": graph.topological_sort(),
    }


@router.post("/photo-solve", response_model=PhotoSolveResponse)
async def photo_solve(
    image: UploadFile = File(...),
    learner_id: str = Form(...),
    request: Request = None,
):
    """拍照搜题：上传数学题图片，启动个性化引导会话。"""
    # 校验文件类型
    if image.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="仅支持 JPEG/PNG 图片")

    # 读取图片
    image_bytes = await image.read()
    if len(image_bytes) > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(status_code=413, detail="图片大小不能超过 10MB")

    # OCR 识别
    from core.ocr_engine import recognize_math_from_photo
    try:
        ocr_result = await recognize_math_from_photo(image_bytes)
    except NotImplementedError:
        from core.ocr_engine import OCRResult
        ocr_result = OCRResult(
            problem_text="[请配置 Vision LLM API Key 以启用 OCR 识别]",
            has_math_formula=True,
            confidence=0.0,
        )

    if 0 < ocr_result.confidence < 0.5:
        raise HTTPException(
            status_code=422,
            detail="图片不太清楚，识别置信度低，请换个角度重拍",
        )

    if "NOT_MATH" in ocr_result.problem_text:
        raise HTTPException(
            status_code=422,
            detail="看起来不是数学题目，请上传数学题图片",
        )

    # 加载学生画像
    orch = request.app.state.orchestrator
    profile = {"learner_id": learner_id, "grade": "初三", "weak_topics": []}
    try:
        from core.student_profile import ProfileStore
        store = ProfileStore()
        await store.init_db()
        saved = await store.load(learner_id)
        if saved:
            profile = saved.model_dump()
    except Exception:
        pass

    # 分析题目
    from core.problem_analyzer import analyze_problem, ProblemAnalysis, SolutionStep
    try:
        analysis = await analyze_problem(ocr_result.problem_text, profile)
    except NotImplementedError:
        analysis = ProblemAnalysis(
            problem_text=ocr_result.problem_text,
            knowledge_points=["未识别"],
            difficulty=3,
            solution_steps=[
                SolutionStep(
                    step_number=1,
                    description="分析题目",
                    key_insight="识别已知条件和求解目标",
                    socratic_prompt="你能告诉我这道题的已知条件是什么，要求什么吗？",
                ),
            ],
            relevance_to_weak=0.0,
        )

    # 创建拍照会话
    session_id = orch.create_photo_session(learner_id, analysis)

    first_step = analysis.solution_steps[0] if analysis.solution_steps else None
    first_guidance = first_step.socratic_prompt if first_step else "让我们开始吧！"

    return PhotoSolveResponse(
        session_id=session_id,
        problem_text=analysis.problem_text,
        knowledge_points=analysis.knowledge_points,
        first_guidance=first_guidance,
    )


@router.post("/photo-session/{session_id}/reply")
async def photo_session_reply(
    session_id: str,
    req: PhotoReplyRequest,
    request: Request,
):
    """学生对引导问题回复。"""
    orch = request.app.state.orchestrator
    result = orch.submit_photo_reply(session_id, req.learner_id, req.reply)

    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在或已结束")

    return result


@router.get("/photo-session/{session_id}")
async def get_photo_session(
    session_id: str,
    request: Request,
):
    """获取拍照会话状态（断线重连用）。"""
    orch = request.app.state.orchestrator
    session = orch.photo_tutor.session_manager.get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "session_id": session.session_id,
        "learner_id": session.learner_id,
        "state": session.state.value,
        "problem_text": session.problem_analysis.problem_text if session.problem_analysis else "",
        "knowledge_points": session.problem_analysis.knowledge_points if session.problem_analysis else [],
        "conversation_history": [
            {"role": e.role, "text": e.text, "msg_type": e.msg_type, "hint_level": e.hint_level}
            for e in session.conversation_history
        ],
        "current_step": session.current_step,
        "total_steps": len(session.solution_steps),
        "hint_count": session.hint_count,
        "created_at": session.created_at,
        "last_activity": session.last_activity,
    }


@router.get("/profile/{learner_id}", response_model=ProfileResponse)
async def get_profile(
    learner_id: str,
    request: Request,
):
    """获取学生画像 + BKT 掌握概览。"""
    orch = request.app.state.orchestrator

    profile_data = None
    try:
        from core.student_profile import ProfileStore
        store = ProfileStore()
        await store.init_db()
        saved = await store.load(learner_id)
        if saved:
            profile_data = saved.model_dump()
    except Exception:
        pass

    progress = orch.get_learner_progress(learner_id)

    return ProfileResponse(
        learner_id=learner_id,
        profile=profile_data,
        progress=progress,
    )
