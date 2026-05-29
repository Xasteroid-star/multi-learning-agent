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


from unittest.mock import AsyncMock, patch
from core.ocr_engine import recognize_math_from_photo


@pytest.mark.asyncio
async def test_recognize_math_from_photo_success():
    """模拟 Vision LLM 成功返回数学题目"""
    image_bytes = b"fake_image_bytes"

    with patch("core.ocr_engine._call_vision_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = OCRResult(
            problem_text="解方程：2x + 5 = 15",
            has_math_formula=True,
            confidence=0.92,
            raw_llm_response="The image shows: 解方程：2x + 5 = 15",
        )
        result = await recognize_math_from_photo(image_bytes)

    assert result.problem_text == "解方程：2x + 5 = 15"
    assert result.has_math_formula is True
    assert result.confidence == 0.92
    mock_llm.assert_called_once_with(image_bytes)


@pytest.mark.asyncio
async def test_recognize_non_math_image():
    """非数学内容应返回 NOT_MATH 标记"""
    image_bytes = b"photo_of_a_cat"

    with patch("core.ocr_engine._call_vision_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = OCRResult(
            problem_text="NOT_MATH",
            has_math_formula=False,
            confidence=0.1,
            raw_llm_response="This is a cat, not math",
        )
        result = await recognize_math_from_photo(image_bytes)

    assert result.problem_text == "NOT_MATH"
    assert result.has_math_formula is False
    assert result.confidence == 0.1
