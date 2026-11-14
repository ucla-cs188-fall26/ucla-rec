"""Turn a PDF into the positioned words the API reads (see rec_normalizers.pool_schedule)."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

from .connect2 import ScrapeError


def pdf_to_content(data: bytes) -> str:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise ScrapeError("pdfplumber is not installed. Run: pip install 'ucla-rec-api[scrape]'") from exc
    if not data.startswith(b"%PDF"):
        raise ScrapeError("that is not a PDF file")
    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            pages.append({
                "width": round(float(page.width), 1), "height": round(float(page.height), 1),
                "words": [
                    {"text": w["text"], "x0": round(w["x0"], 1), "x1": round(w["x1"], 1),
                     "top": round(w["top"], 1), "bottom": round(w["bottom"], 1)}
                    for w in page.extract_words(x_tolerance=1)
                ],
            })
    return json.dumps({"format": "pdf_words", "pages": pages}, separators=(",", ":"))


def download_pdf(url: str, timeout: float = 60.0) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            data = resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ScrapeError(f"could not download the PDF: {exc}") from exc
    if not data.startswith(b"%PDF"):
        raise ScrapeError(
            "that link did not return a PDF. Sharing links (like Box's) open a viewer page; "
            "save the PDF into the project folder and use pdf_file instead"
        )
    return data
