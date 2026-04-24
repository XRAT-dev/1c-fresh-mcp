# 1c-fresh-mcp

**MCP server for 1C:Fresh (Russian cloud accounting).** Lets AI agents (Claude, Cursor, or any MCP client) talk to cloud 1C via its standard OData REST API. Works around the known OData 1C:Fresh limitations (INN filter, `$expand=Товары`, tabular sections), accounts for the 22 % VAT (in force since 2025), and keeps document times in the server's timezone.

Ships with an optional PDF renderer for the «Счёт на оплату» (invoice for payment) printable form.

**🇷🇺 Русская версия → [README.ru.md](README.ru.md)**

---

## Features

- **Catalogs**: counterparties, products/services, organizations, bank payments.
- **Documents**: outgoing invoices (`СчетНаОплатуПокупателю`), sales (`РеализацияТоваровУслуг`) — create, read (incl. tabular section), post, unpost, mark for deletion.
- **Address handling**: counterparty address uses the correct `Вид_Key = ЮрАдресКонтрагента` so it lands in the printable form (1C:Fresh silently drops it otherwise).
- **One-shot invoice POST**: the tabular section `Товары` goes inside the document body (1C:Fresh returns 400 on POST and 405 on PATCH to `_Товары`).
- **INN lookup**: `get_counterparty_by_inn` works around the HTTP 500 that 1C:Fresh returns on `$filter=ИНН eq '…'` by fetching the list and filtering client-side.
- **PDF invoice**: standalone generator with two flavors — *email* (with optional brand banner) and *print* (no banner). Long tables auto-paginate with a repeating header row.

## Available MCP tools

| Group | Tools |
|---|---|
| Health | `check_connection`, `now_nsk` |
| Lookups | `list_organizations`, `list_products`, `search_counterparties`, `get_counterparty_by_inn` |
| Create | `create_counterparty`, `create_counterparty_full`, `make_invoice_item`, `create_invoice` |
| Read | `get_invoice`, `get_sale`, `list_invoices`, `list_sales`, `list_payments` |
| Control | `post_document`, `unpost_document`, `mark_for_deletion` |
| Low-level | `odata_get`, `odata_post`, `odata_patch` |

Every tool carries its own docstring — see `@mcp.tool()` decorators in `server.py`.

## Installation

```bash
git clone https://github.com/XRAT-dev/1c-fresh-mcp.git
cd 1c-fresh-mcp

# 1. Fill in .env
cp .env.example .env
$EDITOR .env           # set FRESH_BASE_URL, FRESH_PASSWORD, etc.

# 2. Install deps and verify connectivity
bash install.sh
```

### Requirements

- **Python ≥ 3.10** (uses PEP 604 `X | None` syntax)
- 1C:Fresh must have the OData interface enabled and a user with the "OData access" role (usually `odata.user`).

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `FRESH_BASE_URL` | ✅ | `https://<region>.1cfresh.com/a/ea/<account>` (no trailing slash) |
| `FRESH_USERNAME` | | Defaults to `odata.user` |
| `FRESH_PASSWORD` | ✅ | OData user password |
| `FRESH_VERIFY_SSL` | | `True` (default) |
| `FRESH_TIMEOUT` | | Seconds, default `30` |
| `FRESH_TZ_OFFSET` | | Hours from UTC (MSK = 3, Novosibirsk = 7) |
| `PDF_BANK_NAME` | | Bank name for the PDF header |
| `PDF_BANK_BIK` | | BIK code |
| `PDF_BANK_CORR_ACC` | | Correspondent account |
| `PDF_BANK_SETTLEMENT_ACC` | | Settlement account |
| `PDF_SIGNER_TITLE` | | "Director" / "Entrepreneur" / etc. |
| `PDF_SIGNER_NAME` | | Name printed on the signature line |
| `PDF_BANNER_PATH` | | Path to a PNG banner (optional) |

## Connect to an MCP client

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

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

**Claude Code** — same block under `mcpServers` in `~/.claude/settings.json`.

See `mcp-config.example.json` for a copy-pasteable example.

## Using the Python connector directly

```python
from connector import Fresh1C
import config

config.assert_configured()
api = Fresh1C(config.BASE_URL, config.USERNAME, config.PASSWORD)

cp = api.get_counterparty_by_inn("1234567890")

item = Fresh1C.make_item(
    nom_guid="<product GUID>",
    qty=1, price=3903.70,
    description="Circuit breaker 63A 3P ABB",
)
inv = api.create_invoice(
    counterparty_guid=cp["Ref_Key"],
    items=[item],
    org_guid="<your org GUID>",
)
api.post_document("СчетНаОплатуПокупателю", inv["Ref_Key"])
```

## PDF invoice

Once `PDF_BANK_*` and `PDF_SIGNER_*` are set in `.env`:

```bash
python3 pdf_invoice.py <invoice_guid>
# → Счёт_<guid[:8]>.pdf          (email variant)
#   Счёт_<guid[:8]>_print.pdf    (print variant, no banner)
```

## Known 1C:Fresh OData quirks handled here

| Limitation | Workaround |
|---|---|
| `$filter` on `ИНН` returns HTTP 500 | `get_counterparty_by_inn` filters client-side |
| `$expand=Товары` returns HTTP 501 | `get_invoice` returns the full document; `Товары` is already inside |
| POST to `.../_Товары` → 400 | `create_invoice` sends `Товары` inside the document body |
| PATCH to `.../_Товары` → 405 | Update by replacing the whole document |
| `DELETE` → 500 | Soft-delete via `mark_for_deletion` (PATCH `DeletionMark=true`) |
| Dates come as `/Date(…)/` | Parsed automatically by `connector.parse_date()` |

## Contributing

Issues and PRs welcome. Keep `.env.example` in sync with any new env variables you add.

## License

MIT — see [LICENSE](LICENSE).
