"""图片与 PDF 的本机校验、文字提取和有界页面渲染。"""
from __future__ import annotations

import base64
import io
import math
import threading
from contextlib import closing, contextmanager
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_MEDIA_BYTES = 10 * 1024 * 1024
MAX_PAGES = 50
MAX_PIXELS = 20_000_000
MAX_PAGE_CHARS = 500_000
MAX_PDF_CHARS = 2_000_000
MAX_RENDER_EDGE = 1536
MAX_IMAGE_BYTES = 2 * 1024 * 1024
IMAGE_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
MEDIA_SUFFIXES = {*IMAGE_FORMATS, ".pdf"}
_PDF_LOCK = threading.RLock()


@contextmanager
def _pdf_guard():
    with _PDF_LOCK:
        try:
            yield
        except pdfium.PdfiumError:
            raise ValueError("PDF 页面损坏或无法解析，请重新导出后添加") from None


def _image(raw: bytes, name: str) -> Image.Image:
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format != IMAGE_FORMATS.get(Path(name).suffix.lower()):
                raise ValueError("图片内容与扩展名不符，请选择 PNG、JPEG 或 WebP 文件")
            if source.width * source.height > MAX_PIXELS or max(source.size) > 16384:
                raise ValueError("图片超过 2000 万像素或单边 16384 像素，请缩小后添加")
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError("暂不支持动画图片，请先导出静态图片")
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", image.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                rgba.close()
                image.close()
                return background
            result = image.convert("RGB")
            image.close()
            return result
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise ValueError("图片损坏、格式不支持或解码尺寸超限，请重新导出后添加") from None


def _document(raw: bytes):
    try:
        document = pdfium.PdfDocument(raw)
    except pdfium.PdfiumError:
        raise ValueError("PDF 无法打开，可能已损坏或有密码保护；请先解锁并重新导出") from None
    if pdfium.raw.FPDF_GetSecurityHandlerRevision(document) >= 0:
        document.close()
        raise ValueError("PDF 有密码保护，请先解锁并重新导出")
    if not 1 <= len(document) <= MAX_PAGES:
        document.close()
        raise ValueError("PDF 必须为 1～50 页，请拆分后添加")
    return document


def _page_text(document, index: int) -> str:
    with closing(document[index]) as page, closing(page.get_textpage()) as text_page:
        if text_page.count_chars() > MAX_PAGE_CHARS:
            raise ValueError("PDF 单页文字过多，请拆分或重新导出")
        return text_page.get_text_range().replace("\x00", "")


def inspect(raw: bytes, name: str) -> tuple[dict, str]:
    if not raw or len(raw) > MAX_MEDIA_BYTES:
        raise ValueError("图片和 PDF 必须为非空且不超过 10 MiB 的文件")
    if Path(name).suffix.lower() != ".pdf":
        with _image(raw, name) as image:
            return {"kind": "image", "mime_type": Image.MIME[IMAGE_FORMATS[Path(name).suffix.lower()]],
                    "width": image.width, "height": image.height, "page_count": 1, "requires_vision": True}, ""
    if not raw.startswith(b"%PDF-"):
        raise ValueError("文件不是有效的 PDF")
    # PDFium 的所有调用（包括关闭资源）必须串行，不能跨请求并行进入本机库。
    with _pdf_guard(), closing(_document(raw)) as document:
        pages, scan_pages, size = [], [], 0
        for index in range(len(document)):
            text = _page_text(document, index)
            size += len(text)
            if size > MAX_PDF_CHARS:
                raise ValueError("PDF 提取文字超过 200 万字符，请拆分后添加")
            pages.append(text)
            if not text.strip():
                scan_pages.append(index + 1)
        return {"kind": "pdf", "mime_type": "application/pdf", "page_count": len(document),
                "scan_pages": scan_pages, "requires_vision": bool(scan_pages)}, "\n".join(pages)


def text_page(raw: bytes, page_number: int) -> str:
    with _pdf_guard(), closing(_document(raw)) as document:
        if not 1 <= page_number <= len(document):
            raise ValueError("PDF 页码超出范围")
        return _page_text(document, page_number - 1)


def render(raw: bytes, item: dict, page_number: int = 1) -> dict:
    if item.get("kind") == "pdf":
        with _pdf_guard(), closing(_document(raw)) as document:
            if not 1 <= page_number <= len(document):
                raise ValueError("PDF 页码超出范围")
            with closing(document[page_number - 1]) as page:
                width, height = page.get_size()
                if not all(math.isfinite(value) and 0 < value <= 100000 for value in (width, height)):
                    raise ValueError("PDF 页面尺寸无效")
                scale = min(2, MAX_RENDER_EDGE / max(width, height))
                with closing(page.render(scale=scale)) as bitmap:
                    image = bitmap.to_pil().convert("RGB")
    else:
        if page_number != 1:
            raise ValueError("图片只有第 1 页")
        image = _image(raw, item["name"])
    with image:
        image.thumbnail((MAX_RENDER_EDGE, MAX_RENDER_EDGE), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
        if output.tell() > MAX_IMAGE_BYTES:
            raise ValueError("图片渲染结果超过 2 MiB，请缩小后重新添加")
        return {"mime_type": "image/jpeg", "data": base64.b64encode(output.getvalue()).decode("ascii"),
                "width": image.width, "height": image.height}
