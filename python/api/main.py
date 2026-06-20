"""
FastAPI 应用入口。

启动方式：
    cd python/
    python -m api.main
    或
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from api.routes import router
from api.websocket import ws_router
from api.orchestrator import AgentOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)

orchestrator: AgentOrchestrator | None = None


def _warmup_ocr():
    """后台预初始化 OCR 引擎（PaddleOCR 下载模型 + 加载），避免首个请求超时。"""
    import os
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    logger = logging.getLogger(__name__)
    try:
        from core.ocr_utils import _get_paddle, _check_tesseract
        t_ok = _check_tesseract()
        logger.info("Tesseract: %s", "ready" if t_ok else "not found")
        logger.info("Warming up PaddleOCR (downloading mobile models if needed)...")
        paddle = _get_paddle()
        if paddle:
            logger.info("PaddleOCR ready")
        else:
            logger.warning("PaddleOCR init failed, will fallback to Tesseract")
    except Exception as e:
        logger.warning("OCR warmup failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global orchestrator
    import asyncio

    orchestrator = AgentOrchestrator()
    app.state.orchestrator = orchestrator
    logging.getLogger(__name__).info("Agent orchestrator started with 6 agents (incl. PhotoTutor)")

    # 后台预热 OCR 引擎
    asyncio.get_event_loop().run_in_executor(None, _warmup_ocr)

    yield
    logging.getLogger(__name__).info("Shutting down")


app = FastAPI(
    title="多Agent智能教育系统",
    description=(
        "6-Agent Mesh+事件驱动架构的个性化学习系统。\n\n"
        "**Agent列表：**\n"
        "- PhotoTutor Agent：拍照搜题 + 苏格拉底引导\n"
        "- Assessment Agent：知识点评估\n"
        "- Tutor Agent：苏格拉底式教学\n"
        "- Curriculum Agent：学习路径规划\n"
        "- Hint Agent：分级提示\n"
        "- Engagement Agent：互动监测"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(ws_router)

# 前端页面
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@app.get("/", response_class=HTMLResponse)
async def index():
    """返回前端页面。"""
    demo_path = FRONTEND_DIR / "demo.html"
    if demo_path.exists():
        return HTMLResponse(demo_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>demo.html not found</h1>", status_code=404)


if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
