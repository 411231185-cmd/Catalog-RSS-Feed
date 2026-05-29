#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка PromIndex-500-FINAL.yml:
 - подбор фото (точный шифр -> нечёткий -> по типу -> заглушка)
 - обогащение описаний кинематикой (z/m/b) из kinematics.json (только подтверждённое)
Работает с YML как с текстом по офферам, чтобы не задеть id/url/categoryId и форматирование.
"""
import re, csv, os, sys, json, datetime

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, "PromIndex-500-FOR-CLAUDE-CODE.yml")
OUT = os.path.join(REPO, "PromIndex-500-FINAL.yml")
LOG = os.path.join(REPO, "changes_log.txt")
LAT_DIR = os.path.join(REPO, "Foto-Directus-Watermark", "Foto-Directus-Latinica")
KIN = os.path.join(REPO, "kinematics.json")

RAW_BASE = "https://raw.githubusercontent.com/411231185-cmd/Catalog-RSS-Feed/main/Foto-Directus-Watermark/Foto-Directus-Latinica/"
ZAGLUSHKA = "https://raw.githubusercontent.com/411231185-cmd/Catalog-RSS-Feed/main/Zaglushka.jpg"

CYR2LAT = {'м':'m','н':'n','к':'k','б':'b','а':'a','т':'t','с':'c','е':'e','о':'o',
           'р':'p','х':'x','в':'v','у':'y','і':'i','ь':'','я':'','л':'l','д':'d','ф':'f'}

def norm(t):
    t = t.lower()
    for c, l in CYR2LAT.items():
        t = t.replace(c, l)
    return t

SHIFR_RE = re.compile(r'\d[0-9a-z]*\.\d+\.\d+')

def shifr_of(text):
    m = SHIFR_RE.search(norm(text).replace('_', '.'))
    return m.group(0) if m else None

# тип детали -> возможные префиксы имён файлов
TYPE_PREFIXES = [
    ("колесо зубчат", ["koleso_zubchatoe"]),
    ("шестерн",       ["shesternya", "shesterni", "koleso_zubchatoe"]),
    ("вал-шестерн",   ["val", "koleso_zubchatoe"]),
    ("вал-рейк",      ["val"]),
    ("валик",         ["val"]),
    ("вал",           ["val", "valy"]),
    ("пиноль",        ["pinol"]),
    ("винт",          ["vint", "khodovoy_vint", "khodovye_vinty"]),
    ("гайк",          ["gayka", "matochnaya_gayka"]),
    ("муфт",          ["mufta"]),
    ("патрон",        ["patron"]),
    ("кулач",         ["kulachok", "kulachki"]),
    ("шпиндел",       ["shpindel", "valy_shpindelnoy_babki"]),
    ("червяч",        ["chervyachnaya", "chervyak"]),
    ("шкив",          ["shkiv"]),
    ("втулк",         ["vtulka"]),
    ("шлиц",          ["shlitsevoy"]),
]

def load_photo_index():
    files = sorted(os.listdir(LAT_DIR))
    files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    by_shifr = {}
    for f in files:
        s = shifr_of(f)
        if s:
            by_shifr.setdefault(s, []).append(f)
    # отсортируем варианты так, чтобы базовое фото (без _2/_3) шло первым
    def variant_key(fn):
        m = re.search(r'_(\d+)\.(?:jpg|jpeg|png)$', fn, re.I)
        return int(m.group(1)) if m else 0
    for s in by_shifr:
        by_shifr[s].sort(key=variant_key)
    return files, by_shifr

def match_photos(name, files, by_shifr):
    """Возвращает (список_файлов, метод)."""
    s = shifr_of(name)
    # 1. точный шифр
    if s and s in by_shifr:
        return by_shifr[s][:5], "exact"
    # 2. нечёткий: совпадение хвоста NN.NNN (без ведущего префикса модели)
    if s:
        tail = ".".join(s.split(".")[-2:])  # напр. 02.172
        cand = []
        for fs, fl in by_shifr.items():
            if fs.endswith(tail) and ".".join(fs.split(".")[-2:]) == tail:
                cand.extend(fl)
        if len(cand) == 1 or (cand and len({shifr_of(c) for c in cand}) == 1):
            return cand[:3], "fuzzy"
    # 3. заглушка (подбор по типу детали отключён — давал чужой номер на фото)
    return None, "zaglushka"

def xml_escape(t):
    return (t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

def main(mode):
    src = open(SRC, encoding='utf-8').read()
    files, by_shifr = load_photo_index()

    offers = list(re.finditer(r'[ \t]*<offer\b.*?</offer>\n', src, re.S))

    # --- режим: только список кандидатов на обогащение ---
    if mode == "candidates":
        out = []
        for m in offers:
            o = m.group(0)
            oid = re.search(r'id="(\d+)"', o).group(1)
            cat = re.search(r'<categoryId>(\d+)</categoryId>', o)
            cat = cat.group(1) if cat else ""
            name = re.search(r'<name>(.*?)</name>', o, re.S).group(1).strip()
            desc = re.search(r'<description>(.*?)</description>', o, re.S).group(1)
            if cat in ("15", "16") and not re.search(r'\bz\s*=', desc):
                s = shifr_of(name)
                out.append({"id": oid, "cat": cat, "name": name, "shifr": s})
        json.dump(out, open(os.path.join(REPO, "candidates.json"), "w", encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print("candidates:", len(out),
              "| колёса(16):", sum(1 for c in out if c["cat"] == "16"),
              "| валы(15):", sum(1 for c in out if c["cat"] == "15"))
        return

    # --- режим сборки ---
    kin = {}
    if os.path.exists(KIN):
        kin = json.load(open(KIN, encoding='utf-8'))

    log = []
    stats = {"exact": 0, "fuzzy": 0, "type": 0, "zaglushka": 0,
             "enriched": 0, "no_data": 0, "already_had_pic": 0}

    def process(m):
        o = m.group(0)
        oid = re.search(r'id="(\d+)"', o).group(1)
        name = re.search(r'<name>(.*?)</name>', o, re.S).group(1).strip()
        indent = "        "  # отступ полей оффера (8 пробелов)

        # --- ФОТО ---
        if '<picture>' in o:
            stats["already_had_pic"] += 1
        else:
            pics, method = match_photos(name, files, by_shifr)
            stats[method] += 1
            if pics:
                urls = [RAW_BASE + p for p in pics]
                logsrc = method + ": " + ", ".join(pics)
            else:
                urls = [ZAGLUSHKA]
                logsrc = "zaglushka: Zaglushka.jpg"
            pic_block = "".join("{}<picture>{}</picture>\n".format(indent, u) for u in urls)
            # вставляем перед <description>
            o = re.sub(r'(\n[ \t]*<description>)',
                       "\n" + pic_block.rstrip("\n") + r"\1", o, count=1)
            log.append("offer {} | {} | ФОТО: {}".format(oid, name, logsrc))

        # --- КИНЕМАТИКА ---
        s = shifr_of(name)
        desc_m = re.search(r'(<description>)(.*?)(</description>)', o, re.S)
        desc = desc_m.group(2)
        cat = re.search(r'<categoryId>(\d+)</categoryId>', o)
        cat = cat.group(1) if cat else ""
        if cat in ("15", "16") and not re.search(r'\bz\s*=', desc) and oid in kin_byid:
            entry = kin_byid[oid]
            parts = []
            if entry.get("z"):
                parts.append("z = {}".format(entry["z"]))
            if entry.get("m"):
                parts.append("m = {}".format(entry["m"]))
            if entry.get("b"):
                parts.append("b = {} мм".format(entry["b"]))
            if parts:
                tail = " (блок зубчатый)" if entry.get("block") else ""
                ins = xml_escape("Параметры зацепления: " + ", ".join(parts) + tail + ". ")
                newdesc = ins + desc.lstrip()
                stats["enriched"] += 1
                log.append("offer {} | {} | КИНЕМАТИКА: {}{} (источник: {})".format(
                    oid, name, ", ".join(parts), tail, entry.get("source", "")))
                o = o[:desc_m.start(2)] + newdesc + o[desc_m.end(2):]
            else:
                # шифр не найден ни в таблицах, ни на сайте — оставляем описание без кинематики
                stats["no_data"] += 1
                log.append("offer {} | {} | КИНЕМАТИКА: не найдена (шифр {}) — описание оставлено без z/m".format(oid, name, s))
        return o

    # индекс kinematics по id оффера
    kin_byid = kin if isinstance(kin, dict) else {}

    new_src = src
    # перестроим заново: заменим каждый оффер
    result_parts = []
    last = 0
    for m in offers:
        result_parts.append(src[last:m.start()])
        result_parts.append(process(m))
        last = m.end()
    result_parts.append(src[last:])
    out_text = "".join(result_parts)

    # имя файла итоговый + дата
    today = datetime.date.today().isoformat()
    out_text = re.sub(r'(<yml_catalog date=")[^"]*(")', r'\g<1>' + today + r'\g<2>', out_text, count=1)

    # удаление упоминания стороннего бренда (правило: только «ТД РУССтанкоСбыт»)
    if " заводом «Станкосервис»" in out_text:
        out_text = out_text.replace(" заводом «Станкосервис»", "")
        log.append("offer 409 | БРЕНД: удалено упоминание стороннего завода «Станкосервис» из <name>")

    open(OUT, "w", encoding='utf-8').write(out_text)

    # лог
    with open(LOG, "w", encoding='utf-8') as f:
        f.write("=== ЛОГ СБОРКИ PromIndex-500-FINAL.yml ({}) ===\n\n".format(today))
        f.write("СВОДКА:\n")
        f.write("  Фото — точное совпадение : {}\n".format(stats["exact"]))
        f.write("  Фото — нечёткое          : {}\n".format(stats["fuzzy"]))
        f.write("  Фото — по типу детали    : {}\n".format(stats["type"]))
        f.write("  Фото — заглушка          : {}\n".format(stats["zaglushka"]))
        f.write("  (уже имели фото, не тронуты): {}\n".format(stats["already_had_pic"]))
        f.write("  Описания обогащены z/m (из XLS): {}\n".format(stats["enriched"]))
        f.write("  Кинематика не найдена (оставлено без z/m): {}\n".format(stats["no_data"]))
        f.write("\nДЕТАЛИ:\n")
        for line in log:
            f.write(line + "\n")

    print("STATS:", json.dumps(stats, ensure_ascii=False))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build")
