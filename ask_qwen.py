import sys, os
from openai import OpenAI
import pymupdf as fitz


API_TOKEN = os.environ.get("LMSTUDIO_TOKEN", "sk-lm-SiS19vpj:RkYqdJxflZNYyP6kGS2h")
API_URL = "http://ii.paragraf.spb.ru/v1"
MODEL = "qwen/qwen3-vl-8b"

client = OpenAI(base_url=API_URL, api_key=API_TOKEN)

def pdf_to_text(pdf_path):
    doc = fitz.open(pdf_path)
    return "\n".join(
        f"\n==== Страница {i} ====\n{page.get_text('text')}" for i, page in enumerate(doc, 1)
    )

def ask(text: str, promt: str, temperature: float = 0.1) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{
            "role": "user", 
            "content": (
                f"{promt}\n\n"
                f"---Начало документа---\n{text}\n---Конец документа---"
            ),
        }],
        temperature=temperature,
    )
    return resp.choices[0].message.content


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python ask_qwen.py <pdf> <вопрос> \"<промпт>\"")
        sys.exit(1)

    pdf, promt = sys.argv[1], sys.argv[2]
    text = pdf_to_text(pdf)
    print(f"[DEBUG] Извлечено {len(text)} символов из {pdf}", file=sys.stderr)
    if len(text) < 500:
        print("[DEBUG] Текст слишком короткий для анализа", file=sys.stderr)

    print(ask(text, promt))