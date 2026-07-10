"""REST API 路由。"""

from __future__ import annotations

from typing import Optional

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
    profile: Optional[dict] = None
    progress: Optional[dict] = None


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "multi-agent-education", "agents": 7}


@router.get("/llm-test")
async def llm_test():
    """测试 LLM API 连接。"""
    from openai import OpenAI
    from config.settings import settings
    import time

    result = {"providers": []}

    # 测试 OpenAI/DeepSeek
    if settings.openai_api_key:
        t0 = time.time()
        try:
            client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
            resp = client.chat.completions.create(
                model=settings.openai_model,
                messages=[{"role": "user", "content": "回复: OK"}],
                max_tokens=10, timeout=10.0,
            )
            elapsed = time.time() - t0
            result["providers"].append({
                "name": "openai",
                "base_url": settings.openai_base_url,
                "model": settings.openai_model,
                "status": "ok",
                "response": resp.choices[0].message.content.strip(),
                "latency_sec": round(elapsed, 2),
            })
        except Exception as e:
            result["providers"].append({
                "name": "openai",
                "base_url": settings.openai_base_url,
                "model": settings.openai_model,
                "status": "fail",
                "error": str(e)[:200],
                "latency_sec": round(time.time() - t0, 2),
            })
    else:
        result["providers"].append({"name": "openai", "status": "not_configured"})

    # 测试 MiniMax
    if settings.minimax_api_key:
        t0 = time.time()
        try:
            client = OpenAI(api_key=settings.minimax_api_key, base_url="https://api.minimaxi.com/v1")
            resp = client.chat.completions.create(
                model=settings.minimax_model,
                messages=[{"role": "user", "content": "回复: OK"}],
                max_tokens=10, timeout=10.0,
            )
            elapsed = time.time() - t0
            result["providers"].append({
                "name": "minimax",
                "model": settings.minimax_model,
                "status": "ok",
                "response": resp.choices[0].message.content.strip(),
                "latency_sec": round(elapsed, 2),
            })
        except Exception as e:
            result["providers"].append({
                "name": "minimax",
                "model": settings.minimax_model,
                "status": "fail",
                "error": str(e)[:200],
                "latency_sec": round(time.time() - t0, 2),
            })
    else:
        result["providers"].append({"name": "minimax", "status": "not_configured"})

    return result


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
    image: Optional[UploadFile] = File(None),
    learner_id: str = Form(...),
    problem_text: str = Form(""),
    request: Request = None,
):
    """拍照搜题：上传数学题图片或直接输入文字，启动个性化引导会话。"""
    ocr_text = problem_text.strip()

    # 如果有图片，尝试 OCR
    if image is not None and image.filename:
        if image.content_type not in ("image/jpeg", "image/png", "image/jpg"):
            raise HTTPException(status_code=400, detail="仅支持 JPEG/PNG 图片")

        image_bytes = await image.read()
        if len(image_bytes) > 10 * 1024 * 1024:  # 10MB
            raise HTTPException(status_code=413, detail="图片大小不能超过 10MB")

        import logging
        import tempfile
        from pathlib import Path

        _logger = logging.getLogger(__name__)

        ocr_blocks = []
        try:
            # 保存上传的图片为临时文件（PaddleOCR/Tesseract 需要文件路径）
            with tempfile.NamedTemporaryFile(
                suffix=".jpg", delete=False
            ) as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            try:
                from core.ocr_utils import ocr_image, ocr_diagnostics, preprocess_image
                _logger.info("OCR engines available: %s", ocr_diagnostics())
                # 先预处理图片（灰度 + 二值化），提升 Tesseract 识别率
                try:
                    _ = preprocess_image(tmp_path)
                except Exception:
                    pass  # 预处理失败不影响后续
                ocr_blocks = ocr_image(tmp_path, engine="auto", preprocess=True)
                _logger.info("OCR result: %d blocks", len(ocr_blocks))
            finally:
                # 清理临时文件
                Path(tmp_path).unlink(missing_ok=True)

            if ocr_blocks:
                ocr_text = "\n".join(b.text for b in ocr_blocks)
                # 只计算有实际文字内容的块的置信度
                valid_blocks = [b for b in ocr_blocks if b.confidence > 0 and len(b.text.strip()) > 0]
                avg_conf = sum(b.confidence for b in valid_blocks) / len(valid_blocks) if valid_blocks else 0
                _logger.info("OCR text (conf=%.2f, valid_blocks=%d/%d): %s",
                             avg_conf, len(valid_blocks), len(ocr_blocks), ocr_text[:200])
                # 如果完全没有有效块才报错
                if not valid_blocks and not ocr_text.strip():
                    raise HTTPException(
                        status_code=422,
                        detail="图片不太清楚，识别置信度低，请换个角度重拍",
                    )
            elif not ocr_text:
                raise HTTPException(
                    status_code=422,
                    detail="OCR 未能识别到文字，请在下方直接输入题目文字",
                )
        except HTTPException:
            raise
        except Exception as e:
            _logger.exception("OCR failed")
            if not ocr_text:
                raise HTTPException(
                    status_code=422,
                    detail=f"OCR 识别失败: {e}",
                )

    if not ocr_text:
        raise HTTPException(
            status_code=400,
            detail="请上传图片或直接输入题目文字",
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
        analysis = await analyze_problem(ocr_text, profile)
    except NotImplementedError:
        analysis = ProblemAnalysis(
            problem_text=ocr_text,
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


@router.get("/profiles")
async def list_profiles(request: Request):
    """列出所有已保存的学生画像（用于选择器）。"""
    try:
        from core.student_profile import ProfileStore
        store = ProfileStore()
        await store.init_db()

        import aiosqlite
        async with aiosqlite.connect(store.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT learner_id, name, grade, total_sessions, total_photo_solves, "
                "curiosity_score, creativity_score, collaboration_score, "
                "resilience_score, communication_score, "
                "updated_at FROM student_profiles ORDER BY updated_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()

        profiles = []
        for row in rows:
            profiles.append({
                "learner_id": row["learner_id"],
                "name": row["name"],
                "grade": row["grade"],
                "total_sessions": row["total_sessions"],
                "total_photo_solves": row["total_photo_solves"],
                "five_forces": {
                    "curiosity": row["curiosity_score"],
                    "creativity": row["creativity_score"],
                    "collaboration": row["collaboration_score"],
                    "resilience": row["resilience_score"],
                    "communication": row["communication_score"],
                },
                "updated_at": row["updated_at"],
            })
        return {"profiles": profiles, "total": len(profiles)}
    except Exception as e:
        return {"profiles": [], "total": 0, "error": str(e)}
# Prompt 资产库管理 API
# ──────────────────────────────────────────────

@router.get("/prompts")
async def list_prompt_templates(request: Request):
    """列出所有 Prompt 模板。"""
    lib = request.app.state.prompt_library
    if lib:
        return {"status": "ok", "templates": lib.list_all()}
    return {"status": "error", "message": "Prompt library not initialized"}


@router.post("/prompts/reload")
async def reload_prompt_templates(request: Request):
    """热加载 Prompt 模板（无需重启）。"""
    lib = request.app.state.prompt_library
    if lib:
        lib.reload()
        return {"status": "ok", "templates": lib.list_all()}
    return {"status": "error", "message": "Prompt library not initialized"}


# ──────────────────────────────────────────────
# 成长追踪 API（Phase 2: 五力观察 + 成长时间线 + 报告）
# ──────────────────────────────────────────────

class RecordObservationRequest(BaseModel):
    learner_id: str
    dimension: str  # "curiosity" | "creativity" | "collaboration" | "resilience" | "communication"
    score: float
    evidence: str
    context: str = ""
    observer: str = ""


class RecordProjectRequest(BaseModel):
    learner_id: str
    project_name: str
    description: str
    related_dimensions: list[str] = []
    media_urls: list[str] = []


@router.post("/growth/observation")
async def record_observation(req: RecordObservationRequest, request: Request):
    """导师记录一次五力观察。"""
    orch = request.app.state.orchestrator
    obs = orch.growth.add_manual_observation(
        req.learner_id, req.dimension, req.score,
        req.evidence, req.context, req.observer,
    )
    return {
        "status": "recorded",
        "learner_id": req.learner_id,
        "dimension": req.dimension,
        "new_score": round(orch.growth.get_learner_model(req.learner_id)
                           .five_forces.get_score(obs.dimension), 1),
    }


@router.post("/growth/project")
async def record_project(req: RecordProjectRequest, request: Request):
    """记录学员作品/项目。"""
    orch = request.app.state.orchestrator
    orch.growth.add_project_record(
        req.learner_id, req.project_name, req.description,
        req.related_dimensions, req.media_urls,
    )
    return {"status": "recorded", "learner_id": req.learner_id, "project": req.project_name}


@router.get("/growth/timeline/{learner_id}")
async def get_growth_timeline(learner_id: str, request: Request):
    """获取学员成长时间线。"""
    orch = request.app.state.orchestrator
    timeline = orch.growth.get_timeline(learner_id)
    return {
        "learner_id": learner_id,
        "event_count": len(timeline.events),
        "milestones": timeline.milestones,
        "camp_sessions": timeline.camp_sessions,
        "recent_events": [
            {
                "event_id": e.event_id,
                "title": e.title,
                "description": e.description,
                "type": e.event_type,
                "timestamp": e.timestamp,
                "dimensions": e.related_dimensions,
                "tags": e.tags,
            }
            for e in timeline.get_recent_events(30)
        ],
    }


@router.get("/growth/forces/{learner_id}")
async def get_five_forces(learner_id: str, request: Request):
    """获取学员五力评估。"""
    orch = request.app.state.orchestrator
    await orch.ensure_learner_loaded(learner_id)  # 从持久化恢复
    learner = orch.growth.get_learner_model(learner_id)
    return {
        "learner_id": learner_id,
        "summary": learner.five_forces.get_summary(),
        "radar_data": learner.five_forces.get_radar_data(),
        "observations_count": len(learner.five_forces.observations),
        "observations": [
            {
                "dimension": o.dimension.value,
                "score": o.score,
                "evidence": o.evidence,
                "context": o.context,
                "observer": o.observer,
                "timestamp": o.timestamp,
            }
            for o in learner.five_forces.observations[-20:]  # 最近20条
        ],
    }


@router.get("/growth/behaviors/{learner_id}")
async def get_behavioral_metrics(learner_id: str, request: Request):
    """获取学员行为信号摘要（趋势二：反馈采纳率、坚持度等）。"""
    orch = request.app.state.orchestrator
    return orch.growth.get_behavioral_summary(learner_id)


@router.get("/growth/forces/{learner_id}/{dimension}")
async def get_force_growth(learner_id: str, dimension: str, request: Request):
    """获取某个五力维度的成长轨迹。"""
    orch = request.app.state.orchestrator
    learner = orch.growth.get_learner_model(learner_id)
    try:
        from core.five_forces_model import ForceDimension
        dim = ForceDimension(dimension)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"未知维度: {dimension}")

    return {
        "learner_id": learner_id,
        "dimension": dimension,
        "current_score": learner.five_forces.get_score(dim),
        "level": learner.five_forces.get_level(dim),
        "growth_trajectory": learner.five_forces.get_dimension_growth(dim),
    }


@router.post("/growth/report/{learner_id}")
async def generate_growth_report(
    learner_id: str,
    child_name: str = "",
    camp_name: str = "",
    season: str = "暑假",
    age: int = 10,
    days: int = 7,
    request: Request = None,
):
    """生成学员成长报告（Markdown 格式）。"""
    orch = request.app.state.orchestrator
    await orch.ensure_learner_loaded(learner_id)  # 从持久化恢复
    learner = orch.growth.get_learner_model(learner_id)
    timeline = orch.growth.get_timeline(learner_id)

    name = child_name or learner_id

    if orch.report_writer is None:
        from agents.growth.report_writer import ReportWriter
        orch.report_writer = ReportWriter()

    report = await orch.report_writer.generate_camp_report(
        child_name=name,
        learner_id=learner_id,
        camp_name=camp_name or "营地",
        season=season,
        age=age,
        days=days,
        five_forces=learner.five_forces,
        timeline=timeline,
    )

    return {
        "learner_id": learner_id,
        "child_name": name,
        "markdown": orch.report_writer.export_markdown(report),
        "sections": [
            {"title": s.title, "content": s.content, "icon": s.icon, "order": s.order}
            for s in sorted(report.sections, key=lambda x: x.order)
        ],
    }
