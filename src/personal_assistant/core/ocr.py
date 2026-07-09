"""OCR 引擎可用性检测与执行（第七阶段 M3）。

OCR 为可选依赖（phase7 §3 不作硬内置）。未安装时返回明确原因供 UI 降级提示。
优先 tesseract + pytesseract（图像）；PDF 需 pdf2image + poppler 渲染。
所有 OCR 库为同步阻塞调用，调用方须在 asyncio.to_thread 中执行。
"""
from __future__ import annotations

import shutil
from pathlib import Path

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def ocr_engine_available() -> tuple[bool, str, str | None]:
    """返回 (available, reason, engine_name)。"""
    if shutil.which("tesseract"):
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401

            return (True, "tesseract + pytesseract 可用", "tesseract")
        except ImportError:
            return (
                False,
                "检测到 tesseract 二进制，但未安装 pytesseract/Pillow"
                "（pip install pytesseract pillow）",
                None,
            )
    try:
        import easyocr  # noqa: F401

        return (True, "easyocr 可用", "easyocr")
    except ImportError:
        pass
    return (
        False,
        "未安装 OCR 引擎（可选：安装 tesseract + pytesseract，或 easyocr）",
        None,
    )


def run_ocr_text(file_path: str) -> str:
    """同步执行 OCR，返回识别文本。不支持的类型或缺失依赖抛异常。

    调用方须在 asyncio.to_thread 中调用以避免阻塞事件循环。
    """
    ext = Path(file_path).suffix.lower()
    if ext in _IMAGE_EXTS:
        import pytesseract
        from PIL import Image

        return pytesseract.image_to_string(
            Image.open(file_path), lang="chi_sim+eng"
        )
    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path
        except ImportError as e:
            raise RuntimeError("PDF OCR 需 pdf2image + poppler") from e
        import pytesseract

        images = convert_from_path(file_path)
        return "\n\n".join(
            pytesseract.image_to_string(img, lang="chi_sim+eng") for img in images
        )
    raise ValueError(f"OCR 不支持的文件类型: {ext}")
