#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_invoice.py — генератор печатной формы счёта на оплату по образцу 1С:Fresh.

Берёт счёт из 1С по GUID, строит PDF максимально близко к штатной печатной форме,
под линией подписи опционально вставляет брендовый баннер во всю ширину.

Запуск:
    python3 pdf_invoice.py <invoice_guid> [output.pdf]
    python3 pdf_invoice.py --last            # последний счёт в базе
"""
import os
import sys
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Table, TableStyle, Paragraph, SimpleDocTemplate,
                                Spacer, Image as RLImage, KeepTogether, HRFlowable)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

from connector import Fresh1C
import config

# ── Шрифты (кириллица, macOS) ────────────────────────────────────
# PT Sans — семейство от ПараТайп, классика русских деловых документов.
# Помимо обычного веса, в коллекции есть "Caption Bold" (index 4),
# оптимизированный для чёткого жирного начертания в корпоративных формах.
PTSANS_COLLECTION = "/System/Library/Fonts/Supplemental/PTSans.ttc"
pdfmetrics.registerFont(TTFont("PTSans", PTSANS_COLLECTION, subfontIndex=0))        # Regular
pdfmetrics.registerFont(TTFont("PTSans-Bold", PTSANS_COLLECTION, subfontIndex=4))   # Caption Bold
pdfmetrics.registerFont(TTFont("PTSans-Italic", PTSANS_COLLECTION, subfontIndex=1)) # Italic
# Регистрируем семейство, чтобы работали <b>, <i> в Paragraph-е
from reportlab.pdfbase.pdfmetrics import registerFontFamily
registerFontFamily("PTSans", normal="PTSans", bold="PTSans-Bold",
                   italic="PTSans-Italic", boldItalic="PTSans-Bold")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
# Путь к брендовому баннеру берём из переменной окружения PDF_BANNER_PATH.
# Если не задан — электронный вариант генерится без картинки.
LOGO_PATH = config.PDF_BANNER_PATH or ""
# Куда класть готовые PDF — рядом с проектом по умолчанию.
OUTPUT_DIR = os.environ.get("PDF_OUTPUT_DIR", PROJECT_DIR)

MONTHS_RU = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

# Правовые формы, которые могут стоять в конце названия (напр. «Иванов А.Л. ИП»)
LEGAL_FORMS = ("ИП", "ООО", "АО", "ПАО", "ЗАО", "ОАО", "НКО", "ГУП", "МУП")


def normalize_org_name(name: str) -> str:
    """Приводит название к виду «<форма> <название>» и убирает пробелы между инициалами.

    Примеры:
        'Иванов А. Л. ИП' → 'ИП Иванов А.Л.'
        'ООО Ромашка'      → 'ООО Ромашка' (не трогаем)
    """
    import re
    s = (name or "").strip().rstrip(",. ")
    # Если форма уже в начале — нечего делать
    for f in LEGAL_FORMS:
        if s.startswith(f + " "):
            return re.sub(r"([А-ЯA-Z])\.\s+([А-ЯA-Z])\.", r"\1.\2.", s)
    # Если форма в конце — переносим вперёд
    for f in LEGAL_FORMS:
        if s.endswith(" " + f):
            body = s[: -(len(f) + 1)].strip()
            s = f"{f} {body}"
            break
    # Инициалы без пробела: «А. Л.» → «А.Л.»
    s = re.sub(r"([А-ЯA-Z])\.\s+([А-ЯA-Z])\.", r"\1.\2.", s)
    return s


# ── Утилиты ──────────────────────────────────────────────────────
def fmt_money(x):
    """140000.0 → '140 000,00'"""
    s = f"{float(x):,.2f}".replace(",", " ").replace(".", ",")
    return s


def fmt_date_ru(iso_date):
    """'2026-04-23T17:23:43' → '23 апреля 2026 г.'"""
    dt = datetime.fromisoformat(iso_date.replace("Z", ""))
    return f"{dt.day} {MONTHS_RU[dt.month - 1]} {dt.year} г."


def fmt_date_short(iso_date):
    """'2026-04-28...' → '28.04.2026'"""
    dt = datetime.fromisoformat(iso_date.replace("Z", ""))
    return dt.strftime("%d.%m.%Y")


# ── Сумма прописью ───────────────────────────────────────────────
_HUND = ["", "сто ", "двести ", "триста ", "четыреста ", "пятьсот ",
         "шестьсот ", "семьсот ", "восемьсот ", "девятьсот "]
_TENS = ["", "", "двадцать ", "тридцать ", "сорок ", "пятьдесят ",
         "шестьдесят ", "семьдесят ", "восемьдесят ", "девяносто "]
_ONES_M = ["", "один ", "два ", "три ", "четыре ", "пять ",
           "шесть ", "семь ", "восемь ", "девять "]
_ONES_F = ["", "одна ", "две ", "три ", "четыре ", "пять ",
           "шесть ", "семь ", "восемь ", "девять "]
_TEENS = ["десять ", "одиннадцать ", "двенадцать ", "тринадцать ",
          "четырнадцать ", "пятнадцать ", "шестнадцать ",
          "семнадцать ", "восемнадцать ", "девятнадцать "]


def _under_thousand(n, female=False):
    ones = _ONES_F if female else _ONES_M
    result = _HUND[n // 100]
    rem = n % 100
    if 10 <= rem < 20:
        result += _TEENS[rem - 10]
    else:
        result += _TENS[rem // 10] + ones[rem % 10]
    return result


def _plural(n, forms):
    """n + ('рубль','рубля','рублей')"""
    n = abs(n) % 100
    if 10 < n < 20:
        return forms[2]
    n = n % 10
    if n == 1: return forms[0]
    if 2 <= n <= 4: return forms[1]
    return forms[2]


def num_to_words_rub(amount):
    """140000.00 → 'Сто сорок тысяч рублей 00 копеек'"""
    rub = int(amount)
    kop = int(round((amount - rub) * 100))
    parts = []

    millions = rub // 1_000_000
    thousands = (rub % 1_000_000) // 1_000
    ones = rub % 1_000

    if millions:
        parts.append(_under_thousand(millions).strip() + " " +
                     _plural(millions, ("миллион", "миллиона", "миллионов")))
    if thousands:
        parts.append(_under_thousand(thousands, female=True).strip() + " " +
                     _plural(thousands, ("тысяча", "тысячи", "тысяч")))
    if ones or not parts:
        parts.append(_under_thousand(ones).strip())

    text = " ".join(p for p in parts if p).strip()
    text = text[0].upper() + text[1:] if text else "Ноль"
    rub_word = _plural(rub, ("рубль", "рубля", "рублей"))
    return f"{text} {rub_word} {kop:02d} копеек"


# ── Загрузка данных счёта ────────────────────────────────────────
def load_invoice(api, guid):
    inv = api._get(f"Document_СчетНаОплатуПокупателю(guid'{guid}')")
    cp = api._get(f"Catalog_Контрагенты(guid'{inv['Контрагент_Key']}')")
    org = api._get(f"Catalog_Организации(guid'{inv['Организация_Key']}')")

    # Собираем строки с названиями номенклатуры и артикулом
    items = []
    for row in inv.get("Товары", []):
        nom = api._get(f"Catalog_Номенклатура(guid'{row['Номенклатура']}')")
        unit = "шт"
        try:
            ed = api._get(f"Catalog_ЕдиницыИзмерения(guid'{nom['ЕдиницаИзмерения_Key']}')")
            unit = ed.get("Description", "шт")
        except Exception:
            pass
        items.append({
            "num": int(row["LineNumber"]),
            "article": nom.get("Артикул", "") or "",
            "name": row.get("Содержание") or nom.get("Description", ""),
            "qty": float(row["Количество"]),
            "unit": unit,
            "price": float(row["Цена"]),
            "sum": float(row["Сумма"]),
            "vat": float(row["СуммаНДС"]),
            "vat_rate": row.get("СтавкаНДС", "") or "",  # напр. "НДС22"
        })

    # Адрес контрагента и организации (первая строка КонтактнаяИнформация с типом «Адрес»)
    def get_addr(obj):
        for ki in obj.get("КонтактнаяИнформация", []) or []:
            if ki.get("Тип") == "Адрес":
                return ki.get("Представление", "")
        return ""

    return {
        # "0000-000018" → "18"
        "number": inv["Number"].split("-")[-1].lstrip("0") or inv["Number"],
        "date": inv["Date"],
        "due_date": inv["Date"],  # TODO: +5 дней или поле
        "sum_total": float(inv["СуммаДокумента"]),
        "includes_vat": inv.get("СуммаВключаетНДС", True),
        "items": items,
        "supplier": {
            "name": normalize_org_name(org.get("Description", "")),
            "inn": org.get("ИНН", ""),
            "kpp": org.get("КПП", ""),
            "addr": get_addr(org),
        },
        "buyer": {
            "name": cp.get("НаименованиеПолное") or cp.get("Description", ""),
            "inn": cp.get("ИНН", ""),
            "kpp": cp.get("КПП", ""),
            "addr": get_addr(cp),
        },
    }


# ── Построение PDF ───────────────────────────────────────────────
def build_pdf(data, out_path, bank_info=None, with_banner=True):
    """Построение PDF через Platypus — с автопереносом таб. товаров на N страниц.

    with_banner=True  → электронный вариант: если задан PDF_BANNER_PATH — вставит баннер.
    with_banner=False → печатный вариант: баннера нет, линия «Предприниматель…»
                        ставится сразу под блоком условий оплаты.
    """
    if bank_info is None:
        # По умолчанию тянем реквизиты из переменных окружения (см. .env)
        bank_info = {
            "bank": config.PDF_BANK["name"],
            "bik": config.PDF_BANK["bik"],
            "ks": config.PDF_BANK["corr_acc"],
            "rs": config.PDF_BANK["settlement_acc"],
        }

    W, H = A4
    MARGIN = 15 * mm
    FONT = "PTSans"
    BOLD = "PTSans-Bold"

    # ── Стили абзацев (единый корпус 9pt; только заголовок 14pt) ─
    BODY = 9
    st_small = ParagraphStyle("s", fontName=FONT, fontSize=BODY, leading=11)
    st_bold = ParagraphStyle("sb", fontName=BOLD, fontSize=BODY, leading=11)
    st_title = ParagraphStyle("t", fontName=BOLD, fontSize=14, leading=16)
    st_note = ParagraphStyle("nt", fontName=FONT, fontSize=BODY, leading=11)
    st_sumw = ParagraphStyle("sw", fontName=BOLD, fontSize=BODY, leading=11)

    flow = []

    # ── Таблица шапки банка ─────────────────────────────────────
    kpp_str = f'КПП {data["supplier"]["kpp"]}' if data["supplier"]["kpp"] else "КПП"
    h_style = ParagraphStyle("h", fontName=FONT, fontSize=BODY, leading=11)
    header_data = [
        [Paragraph(f'{bank_info["bank"]}<br/>Банк получателя', h_style),
         "БИК", bank_info["bik"]],
        ["", "Сч. №", bank_info["ks"]],
        [Paragraph(f'ИНН {data["supplier"]["inn"]} {kpp_str}<br/>'
                   f'{data["supplier"]["name"]}<br/>Получатель', h_style),
         "Сч. №", bank_info["rs"]],
    ]
    t = Table(header_data, colWidths=[105 * mm, 22 * mm, 53 * mm],
              rowHeights=[10 * mm, 6 * mm, 14 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), BODY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("SPAN", (0, 0), (0, 1)),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 6 * mm))

    # ── Заголовок ───────────────────────────────────────────────
    title = f"Счет на оплату № {data['number']} от {fmt_date_ru(data['date'])}"
    flow.append(Paragraph(f"<b>{title}</b>", st_title))
    flow.append(HRFlowable(width="100%", thickness=1, color=colors.black,
                           spaceBefore=2, spaceAfter=4))

    # ── Поставщик / Покупатель ──────────────────────────────────
    sup = data["supplier"]
    buy = data["buyer"]
    sup_text = f'{sup["name"]}, ИНН {sup["inn"]}'
    if sup["kpp"]:
        sup_text += f', КПП {sup["kpp"]}'
    if sup["addr"]:
        sup_text += f', {sup["addr"]}'
    buy_text = f'{buy["name"]}, ИНН {buy["inn"]}'
    if buy["kpp"]:
        buy_text += f', КПП {buy["kpp"]}'
    if buy["addr"]:
        buy_text += f', {buy["addr"]}'

    parties = [
        [Paragraph("Поставщик<br/>(Исполнитель):", st_small),
         Paragraph(f"<b>{sup_text}</b>", st_bold)],
        [Paragraph("Покупатель<br/>(Заказчик):", st_small),
         Paragraph(f"<b>{buy_text}</b>", st_bold)],
    ]
    t = Table(parties, colWidths=[32 * mm, 148 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    flow.append(t)
    flow.append(HRFlowable(width="100%", thickness=1, color=colors.black,
                           spaceBefore=2, spaceAfter=4))

    # ── Основание ───────────────────────────────────────────────
    flow.append(Paragraph("Основание:", st_small))
    flow.append(Spacer(1, 4 * mm))

    # ── Таблица товаров ─────────────────────────────────────────
    header = ["№", "Артикул", "Товары (работы, услуги)",
              "Кол-во", "Ед.", "Цена", "Сумма"]
    rows = [header]
    # wordWrap='CJK' — переносит длинные артикулы посимвольно (без пробелов)
    st_name = ParagraphStyle("n", fontName=FONT, fontSize=BODY, leading=11)
    st_art = ParagraphStyle("a", fontName=FONT, fontSize=BODY, leading=11,
                            wordWrap="CJK", alignment=TA_CENTER)
    for it in data["items"]:
        rows.append([
            str(it["num"]),
            Paragraph(it["article"], st_art),
            Paragraph(it["name"], st_name),
            f'{it["qty"]:g}',
            it["unit"],
            fmt_money(it["price"]),
            fmt_money(it["sum"]),
        ])

    col_widths = [8 * mm, 26 * mm, 82 * mm, 15 * mm, 10 * mm, 19 * mm, 20 * mm]
    t = Table(rows, colWidths=col_widths, repeatRows=1, splitByRow=True)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), FONT),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (4, 0), (4, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 2 * mm))

    # ── Итоги ───────────────────────────────────────────────────
    total = sum(it["sum"] for it in data["items"])
    vat = sum(it["vat"] for it in data["items"])

    # Подпись «В том числе НДС …» — берём ставку из строк счёта.
    # Если все строки в одной ставке — пишем её; иначе общее «НДС».
    import re as _re
    rates_used = {it.get("vat_rate") for it in data["items"] if it.get("vat_rate")}
    if len(rates_used) == 1:
        r = next(iter(rates_used))
        if r == "БезНДС":
            vat_label = "Без НДС"
        else:
            m = _re.match(r"НДС(\d+)", r)
            vat_label = f"В том числе НДС {m.group(1)}%" if m else "В том числе НДС"
    else:
        vat_label = "В том числе НДС"

    totals_rows = [
        ["", Paragraph("<b>Итого:</b>", st_sumw),
         Paragraph(f"<b>{fmt_money(total)}</b>", st_sumw)],
        ["", Paragraph(f"<b>{vat_label}:</b>", st_sumw),
         Paragraph(f"<b>{fmt_money(vat)}</b>", st_sumw)],
        ["", Paragraph("<b>Всего к оплате:</b>", st_sumw),
         Paragraph(f"<b>{fmt_money(total)}</b>", st_sumw)],
    ]
    t2 = Table(totals_rows, colWidths=[100 * mm, 48 * mm, 32 * mm])
    t2.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    flow.append(t2)
    flow.append(Spacer(1, 1 * mm))

    # ── Сумма прописью ──────────────────────────────────────────
    flow.append(Paragraph(
        f'Всего наименований {len(data["items"])}, на сумму {fmt_money(total)} руб.',
        st_small))
    flow.append(Paragraph(f"<b>{num_to_words_rub(total)}</b>", st_sumw))
    flow.append(Spacer(1, 1 * mm))

    # ── Условия оплаты ──────────────────────────────────────────
    from datetime import timedelta
    due = (datetime.fromisoformat(data["date"].replace("Z", ""))
           .replace(hour=0, minute=0, second=0) + timedelta(days=5))
    cond_lines = [
        f"Оплатить не позднее {due.strftime('%d.%m.%Y')}",
        "Оплата данного счета означает согласие с условиями поставки товара.",
        "Уведомление об оплате обязательно, в противном случае не гарантируется наличие товара на складе.",
        "Товар отпускается по факту прихода денег на р/с Поставщика, самовывозом, при наличии доверенности и паспорта.",
    ]
    for ln in cond_lines:
        flow.append(Paragraph(ln, st_note))
    flow.append(Spacer(1, 3 * mm))  # небольшой отступ между условиями и баннером

    # ── Блок подписи + баннер (держим вместе на одной странице) ─
    signer_title = config.PDF_SIGNER_TITLE or "Руководитель"
    signer_name = config.PDF_SIGNER_NAME or ""
    sig_table = Table(
        [[Paragraph(f"<b>{signer_title}</b>", st_bold),
          Paragraph(f"<b>{signer_name}</b>", st_bold)]],
        colWidths=[90 * mm, 90 * mm],
    )
    sig_table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.75, colors.black),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    banner_block = []
    if with_banner and os.path.exists(LOGO_PATH):
        from PIL import Image as PILImage
        img = PILImage.open(LOGO_PATH)
        ratio = img.height / img.width
        banner_w = W - 2 * MARGIN
        banner_h = banner_w * ratio  # пропорционально, без искажений
        banner = RLImage(LOGO_PATH, width=banner_w, height=banner_h)
        banner_block = [banner, Spacer(1, 1 * mm)]

    # Электронный вариант: баннер → линия подписи.
    # Печатный вариант: только линия подписи сразу под условиями.
    flow.append(KeepTogether([*banner_block, sig_table]))

    # ── Генерируем PDF через Platypus ───────────────────────────
    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=10 * mm,
        title=f"Счет на оплату № {data['number']}",
    )
    doc.build(flow)
    return out_path


# ── main ─────────────────────────────────────────────────────────
def main():
    config.assert_configured()
    api = Fresh1C(config.BASE_URL, config.USERNAME, config.PASSWORD,
                  verify_ssl=config.VERIFY_SSL, timeout=config.REQUEST_TIMEOUT)

    if len(sys.argv) >= 2 and sys.argv[1] != "--last":
        guid = sys.argv[1]
    else:
        invs = api.get_invoices(top=1)
        if not invs:
            print("Нет счетов в базе")
            return 1
        guid = invs[0]["Ref_Key"]
        print(f"Последний счёт: №{invs[0]['Number']} GUID {guid}")

    base = (sys.argv[2] if len(sys.argv) >= 3
            else os.path.join(OUTPUT_DIR, f"Счёт_{guid[:8]}.pdf"))
    # Два варианта: электронный (с баннером) и печатный (без баннера)
    stem, ext = os.path.splitext(base)
    out_email = base
    out_print = f"{stem}_print{ext}"

    data = load_invoice(api, guid)
    build_pdf(data, out_email, with_banner=True)
    build_pdf(data, out_print, with_banner=False)
    print(f"✅ Электронный: {out_email}")
    print(f"✅ Печатный:    {out_print}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
