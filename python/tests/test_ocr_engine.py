# tests/test_ocr_engine.py
import pytest
from core.ocr_engine import OCRResult


def test_ocr_result_creation():
    """OCRResult 应该能用标准字段创建"""
    result = OCRResult(
        problem_text="已知二次函数 f(x)=x²+2x-3，求其顶点坐标",
        has_math_formula=True,
        confidence=0.95,
        raw_llm_response="...",
    )
    assert result.problem_text == "已知二次函数 f(x)=x²+2x-3，求其顶点坐标"
    assert result.has_math_formula is True
    assert result.confidence == 0.95
    assert result.raw_llm_response == "..."


def test_ocr_result_defaults():
    """OCRResult 默认值"""
    result = OCRResult(
        problem_text="test",
        has_math_formula=False,
        confidence=0.0,
    )
    assert result.problem_text == "test"
    assert result.has_math_formula is False
    assert result.confidence == 0.0
    assert result.raw_llm_response == ""
