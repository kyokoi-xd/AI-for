import sys
import pymupdf as fitz

def pdf_to_text(pdf_path, out_path=None):
    doc = fitz.open(pdf_path)
    parts = []
    for i, page in enumerate(doc, 1):
        parts.append(f"\n==== Страница {i} ====\n")
        parts.append(page.get_text("text"))

    text = "\n".join(parts)
    if out_path:
        open(out_path, "w", encoding="utf-8").write(text)
    return text

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python pdf2text.py <путь_к_pdf> [<путь_к_выходному_файлу>]")
        sys.exit(1)

    text = pdf_to_text(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    if len(sys.argv) <= 2:
        print(text)
    else:
        print(f"Ok: {len(text)} символов сохранено в {sys.argv[2]}")