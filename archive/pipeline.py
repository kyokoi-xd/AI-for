# pipeline.py — PDF→JSON→сравнение→Excel.  pip install docling openpyxl rapidfuzz beautifulsoup4
import re, sys, json
from pathlib import Path
from bs4 import BeautifulSoup
from rapidfuzz import fuzz


# ==== ШАГ 1: PDF → markdown → JSON ====

def pdf_to_markdown(pdf_path):
    from docling.document_converter import DocumentConverter
    return DocumentConverter().convert(str(pdf_path)).document.export_to_markdown()


def _money(s):
    if not s: return None
    m = re.search(r'-?\d[\d\s\xa0]*[.,]\d+|-?\d+', str(s))
    if not m: return None
    n = m.group(0).replace(' ', '').replace('\xa0', '').replace(',', '.')
    try: return float(n)
    except ValueError: return None


def _date(s):
    if not s: return None
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', str(s))
    return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}" if m else None


def _wear(s):
    if not s: return None
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(s))
    return float(m.group(1).replace(',', '.')) if m else None


def _clean(s):
    s = (s or '').strip()
    if s and len(s) % 2 == 0 and s[:len(s)//2] == s[len(s)//2:]:
        return s[:len(s)//2]
    return s


def _parse_object(body):
    obj = {k: None for k in [
        'name','object_kind','inventory_number','previous_inventory_number',
        'identification_number','manufacture_date','usage','legal_regime',
        'has_encumbrance','wear_percent','initial_cost','depreciation',
        'residual_cost','market_value','cost_date']}
    obj['location'], obj['legal_document'] = {}, {}
    soup = BeautifulSoup(body, 'html.parser')
    parent = None
    for tr in soup.find_all('tr'):
        cells = [td.get_text(' ', strip=True) for td in tr.find_all(['td','th'], recursive=False)]
        if len(cells) == 3: num, prop, val = cells
        elif len(cells) == 2: num, prop, val = '', cells[0], cells[1]
        else: continue
        prop, val = _clean(prop), (val or '').strip()
        if 'Свойств' in prop or prop in ('№','№№',''): continue
        if num.strip().isdigit(): parent = num.strip()

        if prop == 'Наименование объекта': obj['name'] = val or None
        elif prop == 'Вид объекта': obj['object_kind'] = val or None
        elif prop == 'инвентарный номер': obj['inventory_number'] = val or None
        elif prop == 'предыдущий инвентарный номер': obj['previous_inventory_number'] = val or None
        elif prop == 'идентификационный номер': obj['identification_number'] = val or None
        elif prop == 'дата изготовления': obj['manufacture_date'] = _date(val)
        elif prop == 'Сведения о характере использования объекта (назначение)': obj['usage'] = val or None
        elif prop == 'Правовой режим объекта': obj['legal_regime'] = val or None
        elif prop == 'Наличие обременения на объект': obj['has_encumbrance'] = (val.lower() == 'да') if val else None
        elif prop == 'Состояние объекта (степень износа, %)': obj['wear_percent'] = _wear(val)
        elif prop.startswith('Первоначальная балансовая стоимость'):
            obj['initial_cost'] = _money(val); obj['cost_date'] = obj['cost_date'] or _date(val)
        elif prop.startswith('Амортизация в рублях'): obj['depreciation'] = _money(val)
        elif prop.startswith('Балансовая остаточная стоимость'): obj['residual_cost'] = _money(val)
        elif prop.startswith('Рыночная стоимость'): obj['market_value'] = _money(val)
        elif parent == '2' and prop in ('префикс','уточнение','почтовый индекс','дом','литера','корпус','строение','помещение') and val:
            obj['location'][prop] = val
        elif parent == '5':
            if prop == 'наименование': obj['legal_document']['name'] = val or None
            elif prop == 'дата': obj['legal_document']['date'] = _date(val)
            elif prop == 'номер': obj['legal_document']['number'] = val or None
    if not obj['location']: obj['location'] = None
    if not obj['legal_document']: obj['legal_document'] = None
    return obj


def extract_objects(pdf_path):
    md = pdf_to_markdown(pdf_path)
    pat = re.compile(r'Объект\s+движимого\s+имущества\s*[№#Nn]?\s*\.?\s*(\d+)', re.I)
    ms = list(pat.finditer(md))
    out = []
    for i, m in enumerate(ms):
        end = ms[i+1].start() if i+1 < len(ms) else len(md)
        obj = _parse_object(md[m.end():end])
        obj['object_number'] = int(m.group(1)); obj['object_type'] = 'movable'
        out.append(obj)
    return out


# ==== ШАГ 2: сравнение ====

def diff_fields(old, new):
    diffs = []
    for f, label in [('initial_cost','первоначальная стоимость'),
                     ('depreciation','амортизация'),
                     ('residual_cost','остаточная стоимость')]:
        ov, nv = old.get(f), new.get(f)
        if ov is None or nv is None: continue
        if abs(ov - nv) > 0.01:
            diffs.append({'field':f,'label':label,'old':ov,'new':nv,'delta':nv-ov,
                          'severity':'error' if f == 'initial_cost' else 'warning',
                          'reason':'не должна меняться без переоценки' if f == 'initial_cost' else 'проверить динамику'})
    ov, nv = old.get('depreciation'), new.get('depreciation')
    if ov is not None and nv is not None and nv < ov - 0.01:
        diffs.append({'field':'depreciation','old':ov,'new':nv,'severity':'error',
                      'reason':'амортизация уменьшилась (должна только расти)'})
    if old.get('manufacture_date') and new.get('manufacture_date') \
       and old['manufacture_date'] != new['manufacture_date']:
        diffs.append({'field':'manufacture_date','old':old['manufacture_date'],
                      'new':new['manufacture_date'],'severity':'error',
                      'reason':'дата изготовления изменилась — подмена?'})
    return diffs


def validate_new(o):
    issues = []
    for f in ['name','inventory_number','object_kind','manufacture_date','initial_cost','legal_regime']:
        if o.get(f) in (None, ''):
            issues.append({'type':'missing_field','field':f,'severity':'error',
                           'reason':f'поле «{f}» пустое'})
    if (o.get('initial_cost') or 0) <= 0:
        issues.append({'type':'invalid_cost','severity':'error','reason':'стоимость должна быть > 0'})
    ic, dep, rc = o.get('initial_cost'), o.get('depreciation'), o.get('residual_cost')
    if None not in (ic, dep, rc) and abs(ic - dep - rc) > 1.0:
        issues.append({'type':'inconsistent_costs','severity':'error',
                       'reason':f'первоначальная ({ic}) − аморт. ({dep}) ≠ остаточная ({rc})'})
    return issues


def compare(old_objs, new_objs, fuzzy_threshold=85):
    old_by = {o['inventory_number']: o for o in old_objs if o.get('inventory_number')}
    new_by = {o['inventory_number']: o for o in new_objs if o.get('inventory_number')}
    res = {'matched':[], 'changed':[], 'new':[], 'disposed':[]}

    for inv in set(old_by) | set(new_by):
        old, new = old_by.get(inv), new_by.get(inv)
        if old and new:
            d = diff_fields(old, new)
            if old.get('name') and new.get('name') and fuzz.ratio(old['name'], new['name']) < fuzzy_threshold:
                d.append({'field':'name','old':old['name'],'new':new['name'],
                          'severity':'warning','reason':'наименование сильно изменилось'})
            if d: res['changed'].append({'inventory_number':inv,'diffs':d,
                                         'old_name':old.get('name'),'new_name':new.get('name')})
            else: res['matched'].append(inv)
        elif new:
            issues = validate_new(new)
            for inv_o, o in old_by.items():
                if o.get('name') and new.get('name') and fuzz.ratio(o['name'], new['name']) >= 90:
                    issues.append({'type':'possible_duplicate','severity':'warning',
                                   'reason':f'похоже на {inv_o}: «{o["name"]}»'})
            res['new'].append({'object': new, 'issues': issues})
        else:
            res['disposed'].append(old)
    return res


# ==== ШАГ 3: Excel-отчёт ====

def write_excel(diff, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active; ws.title = "Сводка"
    for r in [("Показатель","Значение"),
              ("Совпало без изменений", len(diff['matched'])),
              ("Изменилось", len(diff['changed'])),
              ("Новых объектов", len(diff['new'])),
              ("Выбыло (нет в новом)", len(diff['disposed']))]:
        ws.append(r)
    for c in ws[1]: c.font = Font(bold=True)

    ws = wb.create_sheet("Изменилось")
    ws.append(["Инв. №","Наименование","Поле","Было","Стало","Δ","Уровень","Комментарий"])
    for ch in diff['changed']:
        for d in ch['diffs']:
            ws.append([ch['inventory_number'], ch['new_name'] or ch['old_name'],
                       d.get('label') or d.get('field'), d.get('old'), d.get('new'),
                       d.get('delta'), d.get('severity'), d.get('reason')])
    for c in ws[1]:
        c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor="DDDDDD")

    ws = wb.create_sheet("Новые")
    ws.append(["Инв. №","Наименование","Стоимость","Дата изг.","Проблемы"])
    for item in diff['new']:
        o = item['object']
        txt = "; ".join(i.get('reason','') for i in item['issues']) or "—"
        ws.append([o.get('inventory_number'), o.get('name'),
                   o.get('initial_cost'), o.get('manufacture_date'), txt])
    for c in ws[1]: c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor="DDDDDD")

    ws = wb.create_sheet("Выбыло")
    ws.append(["Инв. №","Наименование","Остаточная стоимость"])
    for o in diff['disposed']:
        ws.append([o.get('inventory_number'), o.get('name'), o.get('residual_cost')])
    for c in ws[1]: c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor="DDDDDD")

    wb.save(path)


# ==== main ====

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Использование: python pipeline.py <PDF_прошлый_год> <PDF_текущий_год> [отчёт.xlsx]")
        sys.exit(1)
    old_pdf, new_pdf = sys.argv[1], sys.argv[2]
    out_xlsx = sys.argv[3] if len(sys.argv) > 3 else "report.xlsx"

    print(f"[1/3] Извлекаю объекты из {old_pdf}...")
    old_objs = extract_objects(old_pdf)
    print(f"      → найдено объектов: {len(old_objs)}")

    print(f"[2/3] Извлекаю объекты из {new_pdf}...")
    new_objs = extract_objects(new_pdf)
    print(f"      → найдено объектов: {len(new_objs)}")

    print("[3/3] Сравниваю...")
    diff = compare(old_objs, new_objs)
    print(f"      Совпало: {len(diff['matched'])} | Изменилось: {len(diff['changed'])} | "
          f"Новых: {len(diff['new'])} | Выбыло: {len(diff['disposed'])}")

    write_excel(diff, out_xlsx)
    Path(old_pdf).with_suffix('.objects.json').write_text(
        json.dumps(old_objs, ensure_ascii=False, indent=2), encoding='utf-8')
    Path(new_pdf).with_suffix('.objects.json').write_text(
        json.dumps(new_objs, ensure_ascii=False, indent=2), encoding='utf-8')
    Path(out_xlsx).with_suffix('.diff.json').write_text(
        json.dumps(diff, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"Готово: {out_xlsx} (+ .objects.json и .diff.json рядом с PDF)")