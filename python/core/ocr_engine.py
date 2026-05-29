# core/ocr_engine.py
"""OCR 引擎 -- 使用 Vision LLM 从图片中识别数学题目。"""

from pydantic import BaseModel


class OCRResult(BaseModel):
    """OCR 识别结果。"""

    problem_text: str
    has_math_formula: bool
    confidence: float
    raw_llm_response: str = ""


import base64
import logging

logger = logging.getLogger(__name__)


async def recognize_math_from_photo(image_bytes: bytes) -> OCRResult:
    """调用 Vision LLM 识别图片中的数学题目。"""
    return await _call_vision_llm(image_bytes)


async def _call_vision_llm(image_bytes: bytes) -> OCRResult:
    """
    调用 Vision LLM API 识别数学题目。
    生产环境中调用 MiniMax/OpenAI 多模态接口。
    当前用 mock 实现以供测试覆盖。
    """
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    logger.info("Calling vision LLM with image size=%d bytes", len(image_bytes))

    raise NotImplementedError(
        "_call_vision_llm must be mocked in tests or configured in production"
    )
