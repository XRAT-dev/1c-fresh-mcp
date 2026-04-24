# 1c-fresh-mcp

**MCP-сервер для 1С:Fresh** — подключает AI-агентов (Claude, Cursor, любой MCP-клиент) к облачной 1С через стандартный OData REST API. Обходит известные ограничения OData 1С:Fresh (фильтр по ИНН, `$expand=Товары`, табличные части документов), автоматически учитывает НДС 22 % с 2025 г. и часовой пояс сервера 1С.

В комплект входит также генератор PDF печатной формы «Счёт на оплату» с автопереносом таблицы на несколько страниц и опциональным брендовым баннером.

**🇬🇧 English version → [README.md](README.md)**

---

## Возможности

- **Справочники**: контрагенты, номенклатура, организации, поступления.
- **Документы**: счета на оплату, реализации товаров и услуг — создание, получение (с табличной частью!), проведение, отмена проведения, пометка на удаление.
- **Контрагент с адресом**: правильный `Вид_Key = ЮрАдресКонтрагента` — адрес попадает в печатную форму счёта (иначе 1С:Fresh молча его игнорирует).
- **Счёт «одним POST-ом»**: таб. часть `Товары` упаковывается в тело документа (в OData 1С:Fresh POST в `_Товары` возвращает 400, PATCH — 405).
- **Обход 500-ки на `$filter` по ИНН**: `get_counterparty_by_inn` тянет список и фильтрует на клиенте.
- **Печатная форма PDF**: собственный шаблон счёта с двумя вариантами — электронный (с баннером) и печатный (без). Автоперенос длинных таблиц на следующие страницы, шапка повторяется.

## Состав MCP-инструментов

| Группа | Инструменты |
|---|---|
| Проверка | `check_connection`, `now_nsk` |
| Справочники | `list_organizations`, `list_products`, `search_counterparties`, `get_counterparty_by_inn` |
| Создание | `create_counterparty`, `create_counterparty_full`, `make_invoice_item`, `create_invoice` |
| Документы | `get_invoice`, `get_sale`, `list_invoices`, `list_sales`, `list_payments` |
| Управление | `post_document`, `unpost_document`, `mark_for_deletion` |
| Низкоуровневое | `odata_get`, `odata_post`, `odata_patch` |

Полное описание каждого инструмента — в `server.py` (docstring-и каждого `@mcp.tool()`).

## Установка

```bash
git clone https://github.com/XRAT-dev/1c-fresh-mcp.git
cd 1c-fresh-mcp

# 1. Заполнить .env
cp .env.example .env
$EDITOR .env           # внесите FRESH_BASE_URL, FRESH_PASSWORD и т.д.

# 2. Поставить зависимости и проверить подключение
bash install.sh
```

### Требования

- **Python ≥ 3.10** (используется синтаксис `X | None`)
- В 1С:Fresh должен быть включён OData-интерфейс и заведён пользователь с правом «Доступ к OData» (обычно `odata.user`).

### Переменные окружения

| Переменная | Обязательная | Описание |
|---|---|---|
| `FRESH_BASE_URL` | ✅ | `https://<region>.1cfresh.com/a/ea/<account>` — без слеша на конце |
| `FRESH_USERNAME` | | По умолчанию `odata.user` |
| `FRESH_PASSWORD` | ✅ | Пароль OData-пользователя |
| `FRESH_VERIFY_SSL` | | `True` (по умолчанию) |
| `FRESH_TIMEOUT` | | Секунд, по умолчанию `30` |
| `FRESH_TZ_OFFSET` | | Смещение TZ сервера 1С от UTC в часах (Мск = 3, Нск = 7) |
| `PDF_BANK_NAME` | | Для генератора PDF — название банка |
| `PDF_BANK_BIK` | | БИК |
| `PDF_BANK_CORR_ACC` | | Корсчёт |
| `PDF_BANK_SETTLEMENT_ACC` | | Расчётный счёт |
| `PDF_SIGNER_TITLE` | | «Руководитель» / «Директор» / «Предприниматель» |
| `PDF_SIGNER_NAME` | | Подписант на линии счёта |
| `PDF_BANNER_PATH` | | Путь к PNG-баннеру (необязательно) |

## Подключение к MCP-клиенту

Пример для **Claude Desktop** (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "1c-fresh": {
      "command": "python3",
      "args": ["/ABSOLUTE/PATH/TO/1c-fresh-mcp/server.py"],
      "env": {"PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

Для **Claude Code** — тот же блок в `~/.claude/settings.json` → `mcpServers`.

Готовый пример: `mcp-config.example.json`.

## Использование из Python (без MCP)

Коннектор можно дёргать и напрямую:

```python
from connector import Fresh1C
import config

config.assert_configured()
api = Fresh1C(config.BASE_URL, config.USERNAME, config.PASSWORD)

# Найти контрагента по ИНН
cp = api.get_counterparty_by_inn("1234567890")

# Собрать строку счёта и создать счёт
item = Fresh1C.make_item(
    nom_guid="<GUID-номенклатуры>",
    qty=1, price=3903.70,
    description="Выключатель автоматический 63А 3P ABB",
)
inv = api.create_invoice(
    counterparty_guid=cp["Ref_Key"],
    items=[item],
    org_guid="<GUID-вашей-организации>",
)
api.post_document("СчетНаОплатуПокупателю", inv["Ref_Key"])
```

## PDF-счёт

После заполнения `PDF_BANK_*` и `PDF_SIGNER_*` в `.env`:

```bash
python3 pdf_invoice.py <invoice_guid>
# → Счёт_<guid[:8]>.pdf         (электронный)
#   Счёт_<guid[:8]>_print.pdf   (без баннера — для печати)
```

## Обходимые ограничения OData 1С:Fresh

| Ограничение | Как обходится в этом сервере |
|---|---|
| `$filter` по `ИНН` → HTTP 500 | `get_counterparty_by_inn` фильтрует на клиенте |
| `$expand=Товары` → HTTP 501 | `get_invoice` возвращает документ целиком — `Товары` уже внутри |
| POST в `…/_Товары` → 400 | `create_invoice` шлёт таб. часть внутри тела документа |
| PATCH в `…/_Товары` → 405 | Меняем таб. часть, обновляя документ целиком |
| `DELETE` → 500 | Используется soft-delete через `mark_for_deletion` (PATCH `DeletionMark=true`) |
| Даты в ответе как `/Date(…)/` | Автоматически парсятся `connector.parse_date()` |

## Вклад

PR и issue — добро пожаловать. Держите в актуальном состоянии `.env.example` при добавлении новых переменных.

## Лицензия

MIT — см. [LICENSE](LICENSE).
