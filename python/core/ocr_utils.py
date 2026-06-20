# core/ocr_utils.py
"""OCR 工具集 —— Tesseract、PaddleOCR、PDF 文字提取的统一切换层。

提供:
    - Tesseract OCR（传统引擎，速度快）
    - PaddleOCR（深度学习引擎，中文/数学公式精度高）
    - PDF 文字直接提取（PyMuPDF，无需 OCR）
    - PDF 页面转图片 + OCR（扫描件/图片型 PDF）
    - 图片预处理工具（去噪、增强对比度）

用法:
    from core.ocr_utils import ocr_image, ocr_pdf, extract_pdf_text

    # 单张图片 OCR
    text = ocr_image("path/to/image.png", engine="paddle")

    # PDF 直接提取（文本型 PDF）
    pages = extract_pdf_text("path/to/doc.pdf")

    # PDF 扫描件 OCR
    pages = ocr_pdf("path/to/scanned.pdf", engine="paddle")

引擎选择:
    - "paddle":  PaddleOCR, 中文/数学精度最高，需 paddleocr 包 (默认)
    - "tesseract": Tesseract, 速度快，需系统安装 tesseract 二进制
    - "auto":     自动尝试 paddle → tesseract → vision_llm
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据类型
# ---------------------------------------------------------------------------

class OCRBlock(BaseModel):
    """OCR 识别的一个文本块。"""
    text: str
    confidence: float
    bbox: Optional[list[float]] = None  # [x1, y1, x2, y2] 归一化坐标


class OCRPage(BaseModel):
    """单页 OCR 结果。"""
    page_num: int
    blocks: list[OCRBlock] = []
    full_text: str = ""


class PDFTextPage(BaseModel):
    """PDF 单页文本提取结果。"""
    page_num: int
    text: str
    blocks: list[dict] = []  # PyMuPDF 原始块


# ---------------------------------------------------------------------------
# 引擎选择与延迟导入
# ---------------------------------------------------------------------------

_PADDLE_INSTANCE = None
_PADDLE_AVAILABLE = None  # None=未检测, True/False
_TESSERACT_AVAILABLE = None  # None=未检测, True/False


def _get_paddle():
    """延迟初始化 PaddleOCR。注意：PaddlePaddle 3.x + PP-OCRv5 在部分 CPU 上有 oneDNN/PIR bug。"""
    global _PADDLE_INSTANCE, _PADDLE_AVAILABLE
    if _PADDLE_AVAILABLE is None:
        try:
            from paddleocr import PaddleOCR
            _PADDLE_INSTANCE = PaddleOCR(
                lang="ch",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="PP-OCRv5_mobile_rec",
            )
            logger.info("PaddleOCR initialized (mobile models, lang=ch)")
            _PADDLE_AVAILABLE = True
        except Exception as e:
            logger.warning("PaddleOCR unavailable: %s", e)
            _PADDLE_INSTANCE = None
            _PADDLE_AVAILABLE = False
    return _PADDLE_INSTANCE


def _check_tesseract() -> bool:
    """检测 Tesseract 是否可用。"""
    global _TESSERACT_AVAILABLE
    if _TESSERACT_AVAILABLE is None:
        try:
            import pytesseract
            # 尝试常见安装路径
            common_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                r"C:\Users\star\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
                "/usr/bin/tesseract",
                "/usr/local/bin/tesseract",
            ]
            for p in common_paths:
                if os.path.exists(p):
                    pytesseract.pytesseract.tesseract_cmd = p
                    logger.info("Tesseract found at: %s", p)
                    _TESSERACT_AVAILABLE = True
                    break
            else:
                # 尝试直接调用
                import shutil
                found = shutil.which("tesseract")
                if found:
                    pytesseract.pytesseract.tesseract_cmd = found
                    _TESSERACT_AVAILABLE = True
                else:
                    logger.info("Tesseract not found on system PATH")
                    _TESSERACT_AVAILABLE = False

            # 配置 tessdata 路径（含自定义中文语言包目录）
            if _TESSERACT_AVAILABLE:
                _setup_tessdata_prefix()

        except ImportError:
            logger.info("pytesseract not installed")
            _TESSERACT_AVAILABLE = False
    return _TESSERACT_AVAILABLE


def _setup_tessdata_prefix():
    """设置 TESSDATA_PREFIX 指向包含 chi_sim 的合并 tessdata 目录。"""
    candidates = [
        os.path.join(os.path.expanduser("~"), "tessdata_full"),
        os.path.join(os.path.expanduser("~"), "tessdata"),
    ]
    for d in candidates:
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "eng.traineddata")):
            os.environ["TESSDATA_PREFIX"] = d
            logger.info("TESSDATA_PREFIX=%s", d)
            return
    logger.debug("No custom tessdata dir found, using Tesseract defaults")


# ---------------------------------------------------------------------------
# 图片预处理
# ---------------------------------------------------------------------------

def preprocess_image(image_path: str | Path) -> "PIL.Image.Image":
    """对图片做预处理：灰度化 + 自适应二值化 + 去噪，提升 OCR 准确率。

    Args:
        image_path: 图片文件路径

    Returns:
        PIL Image 对象（预处理后）
    """
    from PIL import Image, ImageFilter, ImageOps
    import cv2
    import numpy as np

    # 用 PIL 打开
    img = Image.open(image_path).convert("RGB")
    # 转 OpenCV 格式处理
    cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)

    # 自适应阈值二值化
    cv_img = cv2.adaptiveThreshold(
        cv_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
    )

    # 去噪
    cv_img = cv2.fastNlMeansDenoising(cv_img, h=10)

    # 转回 PIL
    return Image.fromarray(cv_img)


# ---------------------------------------------------------------------------
# 图片 OCR
# ---------------------------------------------------------------------------

def ocr_image(
    image_path: str | Path,
    engine: str = "auto",
    lang: str = "chi_sim+eng",
    preprocess: bool = True,
) -> list[OCRBlock]:
    """对单张图片做 OCR 识别。

    Args:
        image_path: 图片路径
        engine:     OCR 引擎: "paddle" | "tesseract" | "auto"
        lang:       语言（仅 tesseract 引擎使用，如 "chi_sim+eng"）
        preprocess: 是否先做图片预处理

    Returns:
        OCRBlock 列表，每个 block 包含文字、置信度、边界框
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    img = preprocess_image(path) if preprocess else None
    img_for_ocr = img if img else str(path)

    # 引擎路由
    if engine == "paddle":
        return _ocr_paddle(img_for_ocr)
    elif engine == "tesseract":
        return _ocr_tesseract(img_for_ocr, lang)
    else:  # auto: Tesseract 优先（稳定可靠），PaddleOCR 可选增强
        # 1) Tesseract（已配置 chi_sim+eng，中文数学识别可靠）
        if _check_tesseract():
            try:
                blocks = _ocr_tesseract(path, lang)
                if blocks:
                    return blocks
            except Exception as e:
                logger.warning("Tesseract failed: %s", e)

        # 2) PaddleOCR 备选（可能受 oneDNN bug 影响）
        paddle = _get_paddle()
        if paddle:
            try:
                return _ocr_paddle(path)
            except Exception as e:
                logger.warning("PaddleOCR failed: %s", e)

        # 3) Vision LLM 最后兜底
        logger.warning("No OCR engine available, trying Vision LLM fallback")
        return _ocr_vision_fallback(path)


def _ocr_paddle(image_input) -> list[OCRBlock]:
    """使用 PaddleOCR 识别。"""
    paddle = _get_paddle()
    if not paddle:
        raise RuntimeError("PaddleOCR not available")

    # PaddleOCR 接受路径字符串或 numpy array
    img_path = image_input if isinstance(image_input, (str, Path)) else None
    img_array = None
    if img_path is None and hasattr(image_input, "__array__"):
        import numpy as np
        img_array = np.array(image_input)

    if img_array is not None:
        result = paddle.predict(img_array)
    else:
        result = paddle.predict(str(img_path))

    blocks = []
    if result and result[0]:
        for line in result[0]:
            bbox = line[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            text = line[1][0]
            confidence = line[1][1]
            # 展平 bbox
            flat_bbox = [bbox[0][0], bbox[0][1], bbox[2][0], bbox[2][1]]
            blocks.append(OCRBlock(text=text, confidence=confidence, bbox=flat_bbox))

    logger.info("PaddleOCR: found %d text blocks", len(blocks))
    return blocks


def _ocr_tesseract(image_input, lang: str = "chi_sim+eng") -> list[OCRBlock]:
    """使用 Tesseract 识别。"""
    if not _check_tesseract():
        raise RuntimeError("Tesseract not available")

    import pytesseract

    img = image_input
    if isinstance(image_input, (str, Path)):
        from PIL import Image
        img = Image.open(image_input)

    # 获取带置信度的数据
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)

    blocks = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if text:
            conf = float(data["conf"][i]) / 100.0
            blocks.append(OCRBlock(
                text=text,
                confidence=conf,
                bbox=[data["left"][i], data["top"][i],
                      data["left"][i] + data["width"][i],
                      data["top"][i] + data["height"][i]],
            ))

    logger.info("Tesseract: found %d text blocks", len(blocks))
    return blocks


def _ocr_vision_fallback(image_path) -> list[OCRBlock]:
    """使用 Vision LLM 兜底（异步调用包装为同步）。"""
    import asyncio
    from .ocr_engine import recognize_math_from_photo

    image_bytes = Path(image_path).read_bytes()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在已有事件循环中创建 future
            import concurrent.futures
            future = asyncio.ensure_future(recognize_math_from_photo(image_bytes))
            # 无法直接 await，返回占位
            logger.warning("Running event loop detected; Vision LLM fallback skipped")
            return [OCRBlock(
                text="[Vision LLM fallback not available in async context — use direct API]",
                confidence=0.0,
            )]
        else:
            result = asyncio.run(recognize_math_from_photo(image_bytes))
    except RuntimeError:
        result = asyncio.run(recognize_math_from_photo(image_bytes))

    return [OCRBlock(
        text=result.problem_text,
        confidence=result.confidence,
    )]


# ---------------------------------------------------------------------------
# PDF 文字提取
# ---------------------------------------------------------------------------

def extract_pdf_text(pdf_path: str | Path) -> list[PDFTextPage]:
    """从 PDF 直接提取文字（适用于文本型 PDF，非扫描件）。

    Args:
        pdf_path: PDF 文件路径

    Returns:
        PDFTextPage 列表，每页包含文字和块信息
    """
    import fitz  # PyMuPDF

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(str(path))
    pages = []

    for i, page in enumerate(doc):
        # 提取文本块
        blocks = page.get_text("blocks")
        text_blocks = []
        full_lines = []

        for b in blocks:
            # block[4] 是文字内容，block[5] 是块类型（0=text, 1=image）
            if b[6] == 0:  # text block
                text = b[4].strip()
                if text:
                    text_blocks.append({
                        "text": text,
                        "bbox": list(b[:4]),
                    })
                    full_lines.append(text)

        pages.append(PDFTextPage(
            page_num=i + 1,
            text="\n".join(full_lines),
            blocks=text_blocks,
        ))

    doc.close()
    logger.info("PyMuPDF: extracted text from %d pages", len(pages))
    return pages


def ocr_pdf(
    pdf_path: str | Path,
    engine: str = "auto",
    lang: str = "chi_sim+eng",
    dpi: int = 200,
    start_page: int = 1,
    end_page: Optional[int] = None,
) -> list[OCRPage]:
    """对 PDF 做 OCR（将页面渲染为图片后逐页识别，适用于扫描件）。

    Args:
        pdf_path:   PDF 文件路径
        engine:     OCR 引擎: "paddle" | "tesseract" | "auto"
        lang:       语言（tesseract 引擎用）
        dpi:        渲染分辨率
        start_page: 起始页 (1-based)
        end_page:   结束页 (1-based, None=到最后一页)

    Returns:
        OCRPage 列表
    """
    import fitz  # PyMuPDF

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(str(path))
    total = doc.page_count
    end = min(end_page or total, total)
    pages = []

    logger.info("OCR scanning PDF: %d pages (engine=%s, dpi=%d)", end - start_page + 1, engine, dpi)

    for i in range(start_page - 1, end):
        page = doc[i]
        # 渲染为图片
        pix = page.get_pixmap(dpi=dpi)
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(pix.tobytes("png")))

        # OCR
        if engine == "paddle":
            blocks = _ocr_paddle(img)
        elif engine == "tesseract":
            blocks = _ocr_tesseract(img, lang)
        else:
            paddle = _get_paddle()
            if paddle:
                try:
                    blocks = _ocr_paddle(img)
                except Exception:
                    blocks = _ocr_tesseract(img, lang) if _check_tesseract() else []
            elif _check_tesseract():
                blocks = _ocr_tesseract(img, lang)
            else:
                blocks = []

        full_text = "\n".join(b.text for b in blocks)
        pages.append(OCRPage(page_num=i + 1, blocks=blocks, full_text=full_text))

    doc.close()
    logger.info("PDF OCR complete: %d pages", len(pages))
    return pages


def extract_pdf_tables(
    pdf_path: str | Path,
    pages: str = "all",
    flavor: str = "lattice",
) -> list:
    """从 PDF 中提取表格数据。

    Args:
        pdf_path: PDF 文件路径
        pages:    要处理的页码，如 "1-3" 或 "all"
        flavor:   表格检测模式: "lattice" (有线框) | "stream" (无线框)

    Returns:
        camelot TableList 对象
    """
    import camelot

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    tables = camelot.read_pdf(str(path), pages=pages, flavor=flavor)
    logger.info("Camelot: extracted %d tables from PDF", len(tables))
    return tables


# ---------------------------------------------------------------------------
# 快速诊断
# ---------------------------------------------------------------------------

def ocr_diagnostics() -> dict:
    """返回已安装 OCR 引擎的诊断信息。"""
    info = {
        "paddle_ocr": False,
        "tesseract": False,
        "pytesseract": False,
        "pymupdf": False,
        "camelot": False,
        "vision_llm": False,
    }

    # PaddleOCR
    try:
        from paddleocr import PaddleOCR
        info["paddle_ocr"] = True
    except ImportError:
        pass

    # Tesseract binary
    info["tesseract"] = _check_tesseract()

    # pytesseract Python 包
    try:
        import pytesseract
        info["pytesseract"] = True
    except ImportError:
        pass

    # PyMuPDF
    try:
        import fitz
        info["pymupdf"] = True
    except ImportError:
        pass

    # Camelot
    try:
        import camelot
        info["camelot"] = True
    except ImportError:
        pass

    # Vision LLM (检查是否配置了 API key)
    try:
        from config.settings import settings
        if settings.openai_api_key or settings.minimax_api_key:
            info["vision_llm"] = True
    except Exception:
        pass

    return info
