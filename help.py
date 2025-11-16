import os

def xlsx_name_from_pdf(pdf_filename: str) -> str:
    base = os.path.basename(pdf_filename)
    root, _ = os.path.splitext(base)
    return f"{root}.xlsx"