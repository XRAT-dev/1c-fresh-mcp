#!/usr/bin/env python3.11
# ============================================================
#  server.py — MCP-сервер для 1С:Fresh (FastMCP SDK)
#  Оборачивает ../connector.py как инструменты для AI-агентов.
# ============================================================
"""
MCP-сервер для 1С:Fresh поверх OData REST API.

Запуск:
    pip install -r requirements.txt
    cp .env.example .env     # и заполни FRESH_BASE_URL / FRESH_PASSWORD
    python3 server.py

Конфиг клиента (Claude Desktop / Claude Code / Cursor — см. mcp-config.example.json):
    {
      "mcpServers": {
        "1c-fresh": {
          "command": "python3",
          "args": ["/ABSOLUTE/PATH/TO/1c-fresh-mcp/server.py"],
          "env": {"PYTHONIOENCODING": "utf-8"}
        }
      }
    }
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from typing import Any

# Импортируем connector.py и config.py из этой же папки
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mcp.server.fastmcp import FastMCP

from connector import Fresh1C, Fresh1CError, НДС_ПО_УМОЛЧАНИЮ
import config

config.assert_configured()


mcp = FastMCP(
    "1c-fresh",
    instructions=(
        "Работа с 1С:Fresh (Бухгалтерия предприятия) через OData.\n"
        "• НДС по умолчанию берётся из FRESH_VAT_DEFAULT (.env), базово НДС22.\n"
        "  Допустимые ставки 2026: НДС22/НДС20/НДС10/НДС7/НДС5/НДС0/БезНДС.\n"
        "• Цены в счетах — ВСЕГДА с НДС (includes_vat=True).\n"
        "• Время документов — Новосибирск (UTC+7).\n"
        "• Перед созданием документа ищи контрагента (get_counterparty_by_inn или "
        "search_counterparties), номенклатуру (list_products), организацию (list_organizations).\n"
        "• Таб. часть `Товары` передаётся СРАЗУ в теле POST документа — POST/PATCH в _Товары не работают.\n"
        "• Удаление объектов через OData DELETE не работает — используй mark_for_deletion.\n"
        "Подробный гайд доступен как ресурс onec://guide."
    ),
)


# ── Ленивый синглтон коннектора ─────────────────────────────
_api: Fresh1C | None = None


def api() -> Fresh1C:
    global _api
    if _api is None:
        _api = Fresh1C(
            config.BASE_URL,
            config.USERNAME,
            config.PASSWORD,
            verify_ssl=config.VERIFY_SSL,
            timeout=config.REQUEST_TIMEOUT,
        )
    return _api


def _dump(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, indent=2, default=str)


# ══════════════════════════════════════════════════════════════
#  ПОДКЛЮЧЕНИЕ / СПРАВОЧНИКИ
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def check_connection() -> str:
    """Проверить подключение к 1С:Fresh. Возвращает статус и параметры базы."""
    try:
        api()._get("Catalog_Организации", {"$top": "1"})
        return _dump({"status": "ok", "base_url": config.BASE_URL, "user": config.USERNAME})
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def list_organizations() -> str:
    """Список своих организаций (юрлиц/ИП). Нужен для org_guid в счетах."""
    try:
        return _dump(api().get_organizations())
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def now_nsk() -> str:
    """Текущее время по Новосибирску (UTC+7) в формате OData YYYY-MM-DDTHH:MM:SS."""
    return _dump({"now": Fresh1C.format_date()})


# ══════════════════════════════════════════════════════════════
#  КОНТРАГЕНТЫ
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def search_counterparties(query: str = "", top: int = 50) -> str:
    """
    Найти контрагентов по подстроке в названии (Description).
    query пустой — вернёт первые top записей.
    """
    try:
        return _dump(api().get_counterparties(top=top, search=query or None))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def get_counterparty_by_inn(inn: str) -> str:
    """Точный поиск контрагента по ИНН. Возвращает объект или {found:false, inn}."""
    try:
        result = api().get_counterparty_by_inn(inn)
        return _dump(result or {"found": False, "inn": inn})
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def create_counterparty(
    name: str,
    inn: str = "",
    kpp: str = "",
    full_name: str = "",
    comment: str = "",
    is_legal: bool = True,
) -> str:
    """
    Создать контрагента (базовая форма, без адреса).

    name — аббревиатура впереди: "ООО Ромашка", "ИП Иванов А.А."
    full_name — СОКРАЩЁННО: "ООО «Ромашка»", НЕ раскрывать до "Общество с ограниченной...".
                Это поле попадает в печатную форму счёта в строку "Покупатель".
    is_legal — True: ЮрЛицо, False: ФизЛицо.
    """
    try:
        return _dump(api().create_counterparty(
            name=name, inn=inn, kpp=kpp,
            full_name=full_name, comment=comment, is_legal=is_legal,
        ))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def create_counterparty_full(
    name: str,
    full_name: str,
    inn: str,
    kpp: str = "",
    address: str = "",
    city: str = "",
    comment: str = "",
    is_legal: bool = True,
) -> str:
    """
    Создать контрагента с юридическим адресом (полная форма).

    Использует Вид_Key ЮрАдресКонтрагента = 3da03500-c669-11f0-ac44-f12d13cb0ca2.
    Если address пустой — эквивалент create_counterparty.
    """
    VID = "3da03500-c669-11f0-ac44-f12d13cb0ca2"
    data: dict[str, Any] = {
        "Description": name,
        "НаименованиеПолное": full_name or name,
        "ИНН": inn,
        "КПП": kpp,
        "Комментарий": comment,
        "ЮридическоеФизическоеЛицо": "ЮридическоеЛицо" if is_legal else "ФизическоеЛицо",
    }
    if address:
        data["КонтактнаяИнформация"] = [{
            "LineNumber": "1",
            "Тип": "Адрес",
            "Вид_Key": VID,
            "ВидДляСписка_Key": VID,
            "Представление": address,
            "Значение": json.dumps({
                "version": 4, "value": address, "type": "Адрес",
                "country": "РОССИЯ", "countryCode": "643",
            }, ensure_ascii=False),
            "Страна": "РОССИЯ",
            "Город": city,
        }]
    try:
        return _dump(api()._post("Catalog_Контрагенты", data))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


# ══════════════════════════════════════════════════════════════
#  НОМЕНКЛАТУРА
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def list_products(search: str = "", top: int = 100) -> str:
    """Список номенклатуры (товары/услуги). search — подстрока в Description."""
    try:
        return _dump(api().get_products(top=top, search=search or None))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


# ══════════════════════════════════════════════════════════════
#  СЧЕТА НА ОПЛАТУ
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def list_invoices(top: int = 50, date_from: str = "", date_to: str = "") -> str:
    """
    Список счетов на оплату покупателям. Сортировка по дате DESC.
    Даты — ISO "YYYY-MM-DDTHH:MM:SS" (опционально).
    """
    try:
        return _dump(api().get_invoices(
            top=top,
            date_from=date_from or None,
            date_to=date_to or None,
        ))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def get_invoice(guid: str) -> str:
    """
    Получить счёт целиком (включая таб. часть Товары) по GUID.
    Это единственный способ достать строки — $expand=Товары возвращает 501.
    """
    try:
        return _dump(api()._get(f"Document_СчетНаОплатуПокупателю(guid'{guid}')"))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def make_invoice_item(
    nom_guid: str,
    qty: float,
    price: float,
    description: str = "",
    nds: str = "",
    line_num: int = 1,
) -> str:
    """
    Подготовить dict строки для счёта. Результат — элемент массива items в create_invoice.

    nom_guid — GUID номенклатуры (поле Номенклатура, не _Key!)
    price    — ЦЕНА ЗА ЕДИНИЦУ С НДС (includes_vat=True)
    nds      — ставка НДС. Пусто → берётся FRESH_VAT_DEFAULT из .env (базово НДС22).
               Допустимо: "НДС22", "НДС20", "НДС10", "НДС7", "НДС5", "НДС0", "БезНДС".
    """
    nds = nds or НДС_ПО_УМОЛЧАНИЮ
    return _dump(Fresh1C.make_item(
        nom_guid=nom_guid, qty=qty, price=price,
        description=description, nds=nds, line_num=line_num,
    ))


@mcp.tool()
def create_invoice(
    counterparty_guid: str,
    items: list[dict],
    org_guid: str = "",
    comment: str = "",
    includes_vat: bool = True,
) -> str:
    """
    Создать счёт на оплату покупателю.

    items — массив dict'ов (результат make_invoice_item).
    Таб. часть Товары передаётся СРАЗУ в теле POST.
    Отдельный POST в _Товары → 400, PATCH в _Товары → 405 — не работают.
    """
    try:
        return _dump(api().create_invoice(
            counterparty_guid=counterparty_guid,
            items=items,
            org_guid=org_guid or None,
            comment=comment,
            includes_vat=includes_vat,
        ))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


# ══════════════════════════════════════════════════════════════
#  РЕАЛИЗАЦИИ / ПЛАТЕЖИ
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def list_sales(top: int = 50, date_from: str = "", date_to: str = "") -> str:
    """Список реализаций товаров и услуг. Сортировка по дате DESC."""
    try:
        return _dump(api().get_sales(
            top=top,
            date_from=date_from or None,
            date_to=date_to or None,
        ))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def get_sale(guid: str) -> str:
    """Получить реализацию целиком по GUID."""
    try:
        return _dump(api()._get(f"Document_РеализацияТоваровУслуг(guid'{guid}')"))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def list_payments(top: int = 50, date_from: str = "") -> str:
    """Список поступлений на расчётный счёт."""
    try:
        return _dump(api().get_payments(top=top, date_from=date_from or None))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


# ══════════════════════════════════════════════════════════════
#  ПРОВЕДЕНИЕ / УДАЛЕНИЕ
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def post_document(doc_type: str, guid: str) -> str:
    """
    Провести документ.
    doc_type: СчетНаОплатуПокупателю, РеализацияТоваровУслуг,
              ПоступлениеНаРасчетныйСчет, ЗаказПокупателя и т.п.
    """
    try:
        api().post_document(doc_type, guid)
        return _dump({"status": "posted", "doc_type": doc_type, "guid": guid})
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def unpost_document(doc_type: str, guid: str) -> str:
    """Отменить проведение документа."""
    try:
        api().unpost_document(doc_type, guid)
        return _dump({"status": "unposted", "doc_type": doc_type, "guid": guid})
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def mark_for_deletion(entity: str, guid: str) -> str:
    """
    Пометить объект на удаление (DeletionMark=True). Откатывается PATCH'ем DeletionMark=False.
    Физическое удаление — только вручную в 1С: Операции → Удаление помеченных объектов.

    entity: полное имя сущности OData, напр.:
        "Document_СчетНаОплатуПокупателю",
        "Catalog_Контрагенты",
        "Catalog_Номенклатура"
    """
    try:
        api()._patch(f"{entity}(guid'{guid}')", {"DeletionMark": True})
        return _dump({"status": "marked_for_deletion", "entity": entity, "guid": guid})
    except Fresh1CError as e:
        return _dump({"error": str(e)})


# ══════════════════════════════════════════════════════════════
#  RAW OData — escape hatch
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def odata_get(resource: str, params: dict | None = None) -> str:
    """
    Сырой GET к OData.
    resource: "Catalog_X" или "Document_X(guid'...')".
    params: dict с $top/$filter/$select/$orderby.
    """
    try:
        return _dump(api()._get(resource, params or {}))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def odata_post(resource: str, data: dict) -> str:
    """Сырой POST к OData. data — тело запроса как объект."""
    try:
        return _dump(api()._post(resource, data))
    except Fresh1CError as e:
        return _dump({"error": str(e)})


@mcp.tool()
def odata_patch(resource: str, data: dict) -> str:
    """Сырой PATCH к OData (частичное обновление)."""
    try:
        api()._patch(resource, data)
        return _dump({"status": "patched", "resource": resource})
    except Fresh1CError as e:
        return _dump({"error": str(e)})


# ══════════════════════════════════════════════════════════════
#  РЕСУРСЫ
# ══════════════════════════════════════════════════════════════

@mcp.resource("onec://guide")
def guide() -> str:
    """Полный гайд по работе с MCP 1С:Fresh (SKILL.md)."""
    p = Path(__file__).parent / "SKILL.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "Гайд не найден — см. README.md"


@mcp.resource("onec://organizations")
def res_orgs() -> str:
    """Список своих организаций из 1С (текущий, без кэша)."""
    try:
        return _dump(api().get_organizations())
    except Fresh1CError as e:
        return _dump({"error": str(e)})


if __name__ == "__main__":
    mcp.run()
