# core/ocr_engine.py
"""OCR 引擎 -- 使用 Vision LLM 从图片中识别数学题目。"""

from pydantic import BaseModel


class OCRResult(BaseModel):
    """OCR 识别结果。"""

    problem_text: str
    has_math_formula: bool
    confidence: float
    raw_llm_response: str = ""
