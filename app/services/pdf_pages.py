from __future__ import annotations

from pathlib import Path


def render_pdf_pages(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    try:
        return _render_with_pymupdf(pdf_path, output_dir, dpi)
    except Exception as first_error:
        try:
            return _render_with_pypdfium2(pdf_path, output_dir, dpi)
        except Exception as second_error:
            raise RuntimeError(
                "PDF rendering failed with both PyMuPDF and pypdfium2. "
                f"PyMuPDF error: {first_error}. pypdfium2 error: {second_error}."
            ) from second_error


def _render_with_pymupdf(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    import fitz

    output_dir.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    with fitz.open(pdf_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image_path = output_dir / f"page_{page_index + 1:03d}.png"
            pixmap.save(image_path)
            pages.append(image_path)
    return pages


def _render_with_pypdfium2(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    import pypdfium2 as pdfium

    output_dir.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    scale = dpi / 72
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        for page_index in range(len(document)):
            page = document[page_index]
            try:
                bitmap = page.render(scale=scale)
                image_path = output_dir / f"page_{page_index + 1:03d}.png"
                bitmap.to_pil().save(image_path)
                pages.append(image_path)
            finally:
                page.close()
    finally:
        document.close()
    return pages
