from typing import List, Optional, Tuple
import fitz  # PyMuPDF
import pymupdf4llm

def maybe_enable_layout() -> bool:
    try:
        import pymupdf.layout  # noqa: F401  # activates advanced layout when installed
        return True
    except Exception:
        return False

def extract_lines_pymupdf4llm(
    pdf_path: str,
    use_layout: bool = True,
    table_strategy: str = "lines_strict",
    page_chunks: bool = True,
) -> Tuple[List[List[str]], List[Optional[str]]]:
    if use_layout:
        maybe_enable_layout()

    doc = fitz.open(pdf_path)
    try:
        try:
            toc_headers = pymupdf4llm.TocHeaders(doc)
        except Exception:
            toc_headers = None
    finally:
        doc.close()

    data = pymupdf4llm.to_markdown(
        pdf_path,
        hdr_info=toc_headers,
        table_strategy=table_strategy,
        page_chunks=page_chunks,
        show_progress=False,
    )

    pages_lines: List[List[str]] = []
    page_headers: List[Optional[str]] = []

    for page_dict in data:
        header_hint = None
        lines: List[str] = []

        for tbl in page_dict.get("tables") or []:
            if header_hint is None and tbl and any((c or "").strip() for c in tbl[0]):
                header_hint = " | ".join((c or "").strip() for c in tbl[0])
            for row in tbl:
                cells = [(c or "").strip() for c in row]
                s = " | ".join(cells).strip()
                if s:
                    lines.append(s)

        md = (page_dict.get("text") or "").strip()
        if md:
            for ln in md.splitlines():
                s = ln.strip()
                if s:
                    lines.append(s)

        seen = set()
        merged = []
        for ln in lines:
            if ln not in seen:
                merged.append(ln)
                seen.add(ln)

        pages_lines.append(merged)
        page_headers.append(header_hint)

    return pages_lines, page_headers