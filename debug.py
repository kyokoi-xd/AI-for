# debug.py
import re, sys

path = sys.argv[1] if len(sys.argv) > 1 else 'karta_2025.md'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

print(f"Размер: {len(text)} символов")
print(f"Первые 300 символов: {repr(text[:300])}")
print(f"\nВхождений 'Объект движимого имущества': {text.count('Объект движимого имущества')}")
print(f"Вхождений '№': {text.count('№')}")

# Все вхождения фразы + что идёт после неё
print("\nВхождения 'Объект движимого имущества':")
for m in re.finditer(r'Объект движимого имущества', text):
    start = max(0, m.start() - 20)
    end = min(len(text), m.end() + 20)
    print(f"  pos={m.start()}: {repr(text[start:end])}")

# Все markdown-заголовки
print("\nMarkdown-заголовки с 'Объект':")
for line in text.splitlines():
    if 'Объект' in line:
        print(f"  {repr(line)}")