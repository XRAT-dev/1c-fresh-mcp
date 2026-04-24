# 1С:Fresh MCP — гайд для агента

Краткий справочник по работе с MCP-сервером `1c-fresh`. Доступен как ресурс
`onec://guide` в любом MCP-клиенте.

## Общие правила

- **НДС по умолчанию — 22%** (`НДС22`), действует с 01.01.2025.
- **Цены в счетах — всегда с НДС** (`includes_vat=True`). Сумма НДС вычисляется
  как `сумма * 0.22 / 1.22` и округляется до копеек.
- **Время документов** — таймзона сервера 1С (`FRESH_TZ_OFFSET`, по умолчанию
  UTC+7 / Новосибирск). Передавай `Date` через `now_nsk()` или `Fresh1C.format_date()`.
- **Табличная часть `Товары`** передаётся сразу в теле POST документа.
  POST в `…/_Товары` → 400, PATCH в `…/_Товары` → 405 — не работают.
- **Удаление через OData DELETE** возвращает 500. Используй
  `mark_for_deletion` (soft-delete через `PATCH DeletionMark=true`).

## Типичный сценарий создания счёта

1. `check_connection` — убедиться, что всё поднято.
2. `list_organizations` — получить `org_guid` своей организации.
3. `get_counterparty_by_inn(inn)` — найти покупателя. Если нет —
   `create_counterparty_full(name, full_name, inn, kpp, address, city)`.
4. `list_products(search=...)` — найти GUID номенклатуры.
5. Собрать строки через `make_invoice_item(nom_guid, qty, price, description)`
   (по одной на каждую позицию, `line_num` проставляется автоматически).
6. `create_invoice(counterparty_guid, items, org_guid, comment)`.
7. `post_document("СчетНаОплатуПокупателю", ref_key)` — провести.

## Частые ошибки и обходы

| Ошибка / ограничение | Обход |
|---|---|
| `$filter=ИНН eq '…'` → HTTP 500 | `get_counterparty_by_inn` листает список и фильтрует клиентом |
| `$expand=Товары` → HTTP 501 | `get_invoice(guid)` уже возвращает документ с `Товары` внутри |
| Адрес контрагента не попадает в печатную форму | `create_counterparty_full` прописывает `Вид_Key = ЮрАдресКонтрагента` |
| Название поля `Date`, не `Дата`; `Posted`, не `Проведен` | Используется в OData-запросах по умолчанию |
| `DELETE` возвращает 500 | `mark_for_deletion` вместо физического удаления |

## PDF-счёт (опционально)

`pdf_invoice.py <invoice_guid>` рендерит два файла:
- `Счёт_<guid[:8]>.pdf` — электронный (с баннером `PDF_BANNER_PATH`, если задан);
- `Счёт_<guid[:8]>_print.pdf` — печатный, без баннера.

Реквизиты банка и подписанта подтягиваются из `.env`
(`PDF_BANK_*`, `PDF_SIGNER_*`).

## Escape hatch

Если нужной обёртки нет, используй низкоуровневые инструменты:
`odata_get(resource, params)`, `odata_post(resource, data)`,
`odata_patch(resource, data)`.
