
import re, json, sys
from bs4 import BeautifulSoup


# ---------- Хелперы значений ----------

def parse_money(s):
    """'518 000,000 ₽ на 01.01.2026' -> 518000.0"""
    if not s:
        return None
    m = re.search(r'-?\d[\d\s\xa0]*[.,]\d+|-?\d+', str(s))
    if not m:
        return None
    num = m.group(0).replace(' ', '').replace('\xa0', '').replace(',', '.')
    try:
        return float(num)
    except ValueError:
        return None


def parse_date(s):
    """'23.12.2025' -> '2025-12-23'"""
    if not s:
        return None
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', str(s))
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"


def parse_money_date(s):
    """-> (value, date_iso)"""
    return parse_money(s), parse_date(s)


def parse_wear(s):
    if not s:
        return None
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(s))
    return float(m.group(1).replace(',', '.')) if m else None


def clean_header(s):
    """'СвойствоСвойство' -> 'Свойство'"""
    s = (s or '').strip()
    if len(s) % 2 == 0 and len(s) > 0:
        half = len(s) // 2
        if s[:half] == s[half:]:
            return s[:half]
    return s


# ---------- Парсинг объектов ----------

def _iter_rows(body):
    """Все строки таблиц в секции (верхний уровень, без дублей из вложенных таблиц)."""
    soup = BeautifulSoup(body, 'html.parser')
    for tr in soup.find_all('tr'):
        cells = [td.get_text(' ', strip=True) for td in tr.find_all(['td', 'th'], recursive=False)]
        if cells:
            yield cells


def parse_movable_object(body):
    obj = {
        "name": None, "object_kind": None,
        "inventory_number": None, "previous_inventory_number": None,
        "identification_number": None, "manufacture_date": None,
        "location": {}, "legal_document": {},
        "usage": None, "legal_regime": None, "has_encumbrance": None,
        "wear_percent": None,
        "initial_cost": None, "depreciation": None,
        "residual_cost": None, "market_value": None,
        "cost_date": None,
    }
    current_parent = None

    for cells in _iter_rows(body):
        if len(cells) == 3:
            num, prop, val = cells
        elif len(cells) == 2:
            num, prop, val = '', cells[0], cells[1]
        else:
            continue

        prop = clean_header(prop)
        val = val.strip() if val else ''

        # заголовки таблицы (в т.ч. битые '№ Свойство')
        if 'Свойств' in prop or prop in ('№', '№№', ''):
            continue

        if num.strip().isdigit():
            current_parent = num.strip()

        # --- поля верхнего уровня ---
        if prop == 'Наименование объекта':
            obj['name'] = val or None
        elif prop == 'Вид объекта':
            obj['object_kind'] = val or None
        elif prop == 'инвентарный номер':
            obj['inventory_number'] = val or None
        elif prop == 'предыдущий инвентарный номер':
            obj['previous_inventory_number'] = val or None
        elif prop == 'идентификационный номер':
            obj['identification_number'] = val or None
        elif prop == 'дата изготовления':
            obj['manufacture_date'] = parse_date(val)
        elif prop == 'Сведения о характере использования объекта (назначение)':
            obj['usage'] = val or None
        elif prop == 'Правовой режим объекта':
            obj['legal_regime'] = val or None
        elif prop == 'Наличие обременения на объект':
            obj['has_encumbrance'] = (val.lower() == 'да') if val else None
        elif prop == 'Состояние объекта (степень износа, %)':
            obj['wear_percent'] = parse_wear(val)
        elif prop.startswith('Первоначальная балансовая стоимость'):
            obj['initial_cost'], d = parse_money_date(val)
            obj['cost_date'] = obj['cost_date'] or d
        elif prop.startswith('Амортизация в рублях'):
            obj['depreciation'], _ = parse_money_date(val)
        elif prop.startswith('Балансовая остаточная стоимость'):
            obj['residual_cost'], _ = parse_money_date(val)
        elif prop.startswith('Рыночная стоимость'):
            obj['market_value'], _ = parse_money_date(val)
        # --- подполя ---
        elif current_parent == '2':  # Местонахождение
            if prop in ('префикс', 'уточнение', 'почтовый индекс', 'дом', 'литера', 'корпус', 'строение', 'помещение') and val:
                obj['location'][prop] = val
        elif current_parent == '5':  # Правоустанавливающий документ
            if prop == 'наименование':
                obj['legal_document']['name'] = val or None
            elif prop == 'дата':
                obj['legal_document']['date'] = parse_date(val)
            elif prop == 'номер':
                obj['legal_document']['number'] = val or None

    if not obj['location']:
        obj['location'] = None
    if not obj['legal_document']:
        obj['legal_document'] = None
    return obj


def split_objects(full_text):
    """Разбиение по заголовкам 'Объект движимого имущества №N' (секции могут занимать несколько страниц)."""
    pat = r'(#{1,6}\s*Объект движимого имущества\s*№\s*(\d+))'
    parts = re.split(pat, full_text)
    result = []
    for i in range(1, len(parts), 3):
        try:
            num = int(parts[i + 1])
        except (ValueError, IndexError):
            continue
        body = parts[i + 2] if i + 2 < len(parts) else ''
        result.append((num, body))
    return result


def parse_all_movable(full_text):
    out = []
    for num, body in split_objects(full_text):
        obj = parse_movable_object(body)
        obj['object_number'] = num
        obj['object_type'] = 'movable'
        out.append(obj)
    return out


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else 'karta_2025.md'
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    data = parse_all_movable(text)
    print(json.dumps(data, ensure_ascii=False, indent=2))