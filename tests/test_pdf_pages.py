from __future__ import annotations

from pathlib import Path

from app.services.pdf_pages import render_pdf_pages


def test_render_pdf_pages_creates_png(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    output_dir = tmp_path / "pages"
    pdf_path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )

    pages = render_pdf_pages(pdf_path, output_dir, dpi=120)

    assert len(pages) == 1
    assert pages[0].name == "page_001.png"
    assert pages[0].read_bytes().startswith(b"\x89PNG")
