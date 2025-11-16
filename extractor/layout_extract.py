from typing import List, Optional, Tuple, Dict, Any
import fitz  # PyMuPDF
import pymupdf4llm

def maybe_enable_layout():
    """
    If PyMuPDF Layout is installed, import it to enhance layout analysis globally.
    Has no effect if the module isn't available.
    """
    try:
        import pymupdf.layout  # noqa: F401
        return True
    except Exception:
        return False

def extract_lines_pymupdf4llm(
    pdf_path: str,
    use_layout: bool = True,
    table_strategy: str = "lines_strict",
    page_chunks: bool = True,
) -> Tuple[List[List[str]], List[Optional[str]]]:
    """
    Use PyMuPDF4LLM to get per-page content and convert it to line strings.
    Tables are rendered as 'c1 | c2 | ...' lines.
    Returns: (pages_lines, pages_header_hints)
    """
    if use_layout:
        maybe_enable_layout()  # enable PyMuPDF Layout if available (improves layout & table detection)

    # Use TOC headers if present for better header detection
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
        hdr_info=toc_headers,    # TOC-driven header levels if available
        table_strategy=table_strategy,
        page_chunks=page_chunks, # get list[dict]: one per page
        show_progress=False,
    )

    pages_lines: List[List[str]] = []
    pages_header_hints: List[Optional[str]] = []

    for page_dict in data:
        header_hint = None
        lines: List[str] = []

        # Tables as lines
        for tbl in page_dict.get("tables") or []:
            if header_hint is None and tbl and any((c or "").strip() for c in tbl[0]):
                header_hint = " | ".join((c or "").strip() for c in tbl[0])
            for row in tbl:
                cells = [(c or "").strip() for c in row]
                line = " | ".join(cells).strip()
                if line:
                    lines.append(line)

        # Markdown text -> lines
        md_text = (page_dict.get("text") or "").strip()
        if md_text:
            for ln in md_text.splitlines():
                s = ln.strip()
                if s:
                    lines.append(s)

        # de-dup preserving order
        seen = set()
        merged = []
        for ln in lines:
            if ln not in seen:
                merged.append(ln)
                seen.add(ln)

        pages_lines.append(merged)
        pages_header_hints.append(header_hint)

    return pages_lines, pages_header_hints