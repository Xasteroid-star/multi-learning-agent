# core/ocr_engine.py
"""OCR 引擎 -- 使用 Vision LLM 从图片中识别数学题目。"""

import base64
import logging

from pydantic import BaseModel


class OCRResult(BaseModel):
    """OCR 识别结果。"""

    problem_text: str
    has_math_formula: bool
    confidence: float
    raw_llm_response: str = ""

logger = logging.getLogger(__name__)


async def recognize_math_from_photo(image_bytes: bytes) -> OCRResult:
    """调用 Vision LLM 识别图片中的数学题目。"""
    return await _call_vision_llm(image_bytes)


OCR_PROMPT = """请仔细识别这张图片中的数学题目内容。要求：
1. 完整提取题目文字和数学公式
2. 数学公式请用LaTeX格式（$包裹）输出
3. 保持题目的结构和编号
4. 如果有图形，请用文字描述图形的关键信息
5. 只输出题目内容，不要解答"""


def _get_llm_client():
    """获取 LLM 客户端（OpenAI 优先，MiniMax 备用）。"""
    from config.settings import settings
    from openai import OpenAI

    if settings.openai_api_key:
        return OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        ), settings.openai_model, "openai"

    if settings.minimax_api_key:
        return OpenAI(
            api_key=settings.minimax_api_key,
            base_url="https://api.minimaxi.com/v1",
        ), settings.minimax_model, "minimax"

    return None, None, None


async def _call_vision_llm(image_bytes: bytes) -> OCRResult:
    """调用 Vision LLM API 识别数学题目。"""
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    logger.info("Calling vision LLM with image size=%d bytes", len(image_bytes))

    client, model, provider = _get_llm_client()
    if client is None:
        logger.warning("No LLM API key configured — returning placeholder")
        return OCRResult(
            problem_text="[请设置 OPENAI_API_KEY 或 MINIMAX_API_KEY 环境变量]",
            has_math_formula=False,
            confidence=0.0,
        )

    logger.info("Using %s provider with model=%s", provider, model)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
            temperature=0.3,
        )
        raw = response.choices[0].message.content or ""
        logger.info("Vision LLM response: %s", raw[:200])
    except Exception as e:
        logger.exception("Vision LLM call failed")
        return OCRResult(
            problem_text=f"[OCR 识别失败: {e}]",
            has_math_formula=False,
            confidence=0.0,
            raw_llm_response=str(e),
        )

    has_math = any(symbol in raw for symbol in ["$", "=", "+", "×", "÷", "√", "²", "³", "∑", "∫"])
    confidence = 0.85 if has_math else 0.4

    return OCRResult(
        problem_text=raw,
        has_math_formula=has_math,
        confidence=confidence,
        raw_llm_response=raw,
    )
