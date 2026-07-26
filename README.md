*English | [Deutsch](README_de.md)*

# pp-mcp — MCP Server for Portfolio Performance

A read-only MCP server that provides filtered account and portfolio data from one or
more [Portfolio Performance](https://www.portfolio-performance.info/) `.portfolio`
files — e.g. to generate reports from them (transactions of an account,
distributions/interest/taxes for a period, etc.).

Files are only **read**, never modified. Supports unencrypted and AES-encrypted
(password-protected) files.

## Terminology

Portfolio Performance uses the word "portfolio" for two different things, which can
be ambiguous — pp-mcp uses these terms consistently everywhere (tool descriptions,
parameters, this README):

- **Source** (parameter `source`) — one complete `.portfolio` file, i.e. one
  configured data source. See `list_data_sources`.
- **Portfolio** (parameter `portfolio_name`) — a securities portfolio/depot *within*
  a source (Portfolio Performance's own internal term for this object). See
  `list_portfolios`.
- **Account** (parameter `account`) — a cash account within a source. See
  `list_accounts`.
- **Security** (parameter `security`) — a stock, fund, ETF, etc. See `list_securities`.

If it's unclear whether "portfolio" refers to a source or a portfolio/depot in a
given context, check `list_data_sources` and `list_portfolios` to see which one
actually matches.

## Example questions

Once connected, you can just ask your AI assistant things like:

- "What securities do I currently hold in my Growth portfolio, and what are they worth?"
- "Show me all dividend payments from my Broker account in 2025."
- "What's the current balance of my Cash account?"
- "How has the value of my Retirement portfolio developed over the last 12 months?"
- "What's my unrealized gain on Apple shares in the Growth portfolio?"
- "Break down my holdings by asset class."
- "What's the latest price of iShares Core MSCI World?"
- "List my savings plans and how much they invest per month."

With multiple configured sources, just name the one you mean (e.g. "in my
retirement-account source") — the assistant will look it up via `list_data_sources`.

## Multiple portfolio files (multi-source)

By default, one instance serves exactly one file (`PP_FILE_PATH`). Via
`PP_PORTFOLIOS_CONFIG` you can instead configure a JSON file with multiple sources
(see `portfolios.json.example`):

```json
[
  {"id": "example1", "label": "Example1", "path": "/data/portfolios/Example1.portfolio", "password": null},
  {"id": "example2", "label": "Example2", "path": "/data/portfolios/Example2.portfolio", "password": null}
]
```

Every tool then gets an additional optional parameter `source` (the `id` from the
config). With exactly one configured source, `source` can be omitted.
`list_data_sources` returns the available `id`+`label` without exposing paths or
passwords. Each source has its own mtime cache.

## Tools

| Tool | Purpose |
|------|-------|
| `list_data_sources` | Configured portfolio sources (id, label) for the `source` parameter of the other tools. |
| `get_file_info` | File metadata: path, modification date, encrypted yes/no, version, base currency, number of accounts/portfolios/securities/transactions, earliest/latest transaction date. |
| `list_accounts` | All accounts (uuid, name, currencyCode, isRetired). |
| `list_portfolios` | All portfolios (uuid, name, reference account, isRetired). |
| `list_securities` | All securities (uuid, name, isin, wkn, tickerSymbol, currencyCode, isRetired). |
| `list_transaction_types` | Valid transaction types as a filter aid. |
| `get_transactions` | Filtered transactions (period, types, account/portfolio/security – each optional), incl. `securityIsin` per transaction. |
| `get_transaction_summary` | Sums and counts per transaction type + total sum for the period. |
| `get_latest_price` | Most recent known price of a security (`latest` field, otherwise the newest historical price). |
| `get_price_history` | Historical daily closing prices for the period (optional `limit` for the last N). |
| `get_price_on` | Price as of a reference date – exact or last price before it (for point-in-time valuations). |
| `list_latest_prices` | Most recent price of **all** securities as an overview. |
| `list_price_feeds` | Price update configuration (feed type + feed URL) of all active securities. |
| `refresh_prices` | Fetch missing, more recent prices via feed – only temporary in memory, see below. |
| `get_holdings` | Portfolio valuation: holdings (quantity × price) as of a reference date, optionally per portfolio. |
| `get_holdings_history` | Value history of the portfolio across multiple reference dates (`daily`/`weekly`/`monthly`) – sums per currency, for charts. |
| `get_unrealized_gains` | Unrealized gains per open position (moving average price, as in PP standard). |
| `get_realized_gains` | Realized gains per security from sales within the period. |
| `get_account_balance` | Account balance of a cash account as of a reference date. |
| `list_taxonomies` | All taxonomies (asset classes, regions, industries, …) with classification tree and assignments. |
| `get_asset_allocation` | Holdings value distributed across the classifications of a taxonomy. |
| `list_investment_plans` | Savings/investment plans with security/portfolio/account, amount and interval. |
| `ping` | Checks whether the server is running. |

`get_transactions` covers both core use cases:
- **Transactions of an account within a period**: set `account` + `date_from`/`date_to`.
- **Portfolio transactions of certain types**: set `portfolio_name` + `types` (+ period).

**For the current account balance use `get_account_balance`, not manual summation of
`get_transactions`:** `get_transactions`/`get_transaction_summary` only filter by the
account primarily referenced in the transaction – for a `CASH_TRANSFER` between two
accounts, the inflow does **not** show up at the destination account (only at the
source account). `get_account_balance` accounts for both sides of `CASH_TRANSFER` as
well as the correct signs of all cash-affecting transaction types and returns the
actual balance.

Account/portfolio/security can be specified as **name or UUID** (case-insensitive).
Dates in ISO format `YYYY-MM-DD`. Amounts are returned as strings (exact decimal
values). All tools except `list_transaction_types` (source-independent) and
`list_data_sources` additionally accept `source` to select the portfolio file in
multi-source operation.

Transaction types: `PURCHASE, SALE, SECURITY_TRANSFER, CASH_TRANSFER, DEPOSIT, REMOVAL,
DIVIDEND, INTEREST, INTEREST_CHARGE, TAX, TAX_REFUND, FEE, FEE_REFUND`.

For the price tools, the security can also be specified via **ISIN, WKN, or ticker**
(instead of name/UUID). Prices are returned as strings; `source` distinguishes
`latest` (most recently fetched price) from `historical` (newest historical closing
price).

`get_holdings` computes the held quantity per security from the transactions
(PURCHASE/SALE, inbound/outbound deliveries, portfolio transfers) and values it with
the price as of the reference date. Without `portfolio_name`, all portfolios are
combined (transfers between portfolios cancel out); without `date`, the most recent
price applies. **No currency conversion:** values are in the security's currency,
sums are reported per currency (`totalsByCurrency`).

`get_holdings_history` repeats the same calculation for a series of reference dates
between `date_from` and `date_to` (inclusive) and returns only `totalsByCurrency` per
date (no individual positions) – intended for value-history charts. Without
`date_from`, the date of the first transaction is used; without `date_to`, today's
date. `interval` controls the resolution: `monthly` (default, month-end dates, the
last point is always `date_to`), `weekly`, or `daily`.

## Fetching missing prices (`refresh_prices`)

Portfolio Performance configures securities with a price feed (`feed`/`feedURL` per
security, visible via `list_price_feeds`). If the `.portfolio` file isn't fully
up to date (e.g. PP hasn't been opened for a while), `refresh_prices` can fetch
missing, newer prices directly via this feed. Currently only the feed type
`GENERIC_HTML_TABLE` with an `ariva.de` host is supported (SSRF-protected: `https`
only, host allowlist, no private/internal IPs) – other feeds (`PP`, `YAHOO`, …) are
skipped and reported as such, not as an error.

The fetched prices land in a **purely temporary in-memory overlay** per portfolio
source – the `.portfolio` file is **never** modified. The overlay only adds dates
missing from the file (existing file prices are never overwritten), and is
automatically taken into account by all price/valuation tools
(`get_latest_price`, `get_price_history`, `get_holdings`, `get_unrealized_gains`,
`get_holdings_history`, …). It is discarded as soon as the file is actually
rewritten (mtime change, e.g. by PP itself) or the server restarts – calling
`refresh_prices` again brings it back up to date if needed.

## Running with Docker

Two compose files for different deployment scenarios:

- **`docker-compose.yml`** — multi-source production deployment (e.g. Synology NAS):
  a directory with multiple `.portfolio` files + `portfolios.json`, `MCP_AUTH_TOKEN`
  required, port bound only to `127.0.0.1`, external Docker networks for
  nginx-proxy-manager and other backends.
- **`docker-compose.dev.yml`** — simple local single-source setup: a single file
  mounted via `PP_HOST_FILE`, no auth required, no external networks.

```bash
cp .env.example .env      # adjust depending on the chosen compose file
docker-compose -f docker-compose.dev.yml up -d --build   # local, single-source
# or
docker-compose up -d --build                              # production, multi-source
```

The MCP server runs on `http://localhost:8080` (streamable-http). See the comments
in the respective compose file and `portfolios.json.example` for the relevant
environment variables.

## Running locally with uv (Docker alternative)

For a local MCP client, `uv` can manage the Python installation and virtual
environment while the client starts `pp-mcp` on demand over stdio:

```bash
uv python install 3.11
uv venv --python 3.11
uv pip install -r requirements.txt
cp .env.example .env
```

In `.env`, set the path used by the process itself (not the Docker mount path)
and select stdio:

```dotenv
PP_FILE_PATH=/absolute/path/to/file.portfolio
MCP_TRANSPORT=stdio
```

For multi-source, set `PP_PORTFOLIOS_CONFIG=/absolute/path/to/portfolios.json`
instead (it takes precedence over `PP_FILE_PATH`/`PP_PASSWORD`). You can verify
the setup from the repository directory:

```bash
uv run --no-project python -m src.main
```

`uv` uses the existing `.venv`; `--no-project` keeps `requirements.txt` as the
dependency source and prevents an unrelated parent `pyproject.toml` from being
discovered. In normal use the MCP client runs this command and controls the
stdio process, so no daemon or listening port is needed. To run the same local
environment as an HTTP server instead, set `MCP_TRANSPORT=streamable-http`.

## Configuring in Claude

The configuration depends on how `pp-mcp` is run:

- For Docker or another persistent HTTP deployment, use the endpoint
  `http://<host>:<port>/mcp` (`/sse` if `MCP_TRANSPORT=sse`).
- For the local `uv` setup, let Claude launch the server over stdio as shown
  below.

**Claude Code with an HTTP server** — via CLI:

```bash
claude mcp add --transport http pp-mcp http://localhost:8080/mcp \
  --header "Authorization: Bearer <MCP_AUTH_TOKEN>"
```

Omit `--header` if `MCP_AUTH_TOKEN` is empty. This writes to `~/.claude.json`
(user scope) or, with `--scope project`, to `.mcp.json` in the current project.
Equivalently, edit the file directly:

```json
{
  "mcpServers": {
    "pp-mcp": {
      "type": "http",
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

Drop the `headers` block entirely if no auth token is configured.

**Claude Desktop with local uv/stdio** — edit the config file at:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "pp-mcp": {
      "command": "/absolute/path/to/uv",
      "args": [
        "--directory", "/absolute/path/to/pp-mcp",
        "run", "--no-project", "python", "-m", "src.main"
      ],
      "env": {
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

Use the absolute path reported by `command -v uv`; GUI applications may not
inherit the shell's `PATH`. Keep `PP_FILE_PATH`, `PP_PASSWORD`, or
`PP_PORTFOLIOS_CONFIG` in the repository's `.env` file rather than duplicating
them in the client configuration.

To connect Claude Desktop to an HTTP deployment instead, use a stdio-to-HTTP
bridge such as [`mcp-remote`](https://www.npmjs.com/package/mcp-remote):

```json
{
  "mcpServers": {
    "pp-mcp": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "http://localhost:8080/mcp",
        "--header", "Authorization: Bearer <MCP_AUTH_TOKEN>"
      ]
    }
  }
}
```

## Using other MCP clients / AI assistants

`pp-mcp` is not Claude-specific — it is a standard MCP server with plain MCP tool
definitions. Clients can either launch it locally over stdio (using the `uv`
command above) or connect to a persistent `streamable-http`/SSE deployment. For
HTTP, point the client at `http://<host>:<port>/mcp` and, if `MCP_AUTH_TOKEN` is
set, add an `Authorization: Bearer <MCP_AUTH_TOKEN>` header. Check the client's
documentation for its stdio process or remote MCP configuration format.

## Switching the portfolio file (macOS)

If you manage multiple `.portfolio` files, `switch-portfolio.sh` lets you quickly
switch between them. The script sets `PP_FILE_PATH` in `.env` and restarts the
server — for local operation, via the launchd service `de.pp-mcp.server`:

```bash
./switch-portfolio.sh --list                                   # show active files
./switch-portfolio.sh /Users/you/Portfolios/Depot.portfolio    # switch + restart
```

`--list` hides backups (`*.backup*`) and conflict copies (`*conflicted*`).
The paths (`APP_DIR`, `PORTFOLIO_DIR`, `SERVICE`) are defined as constants at the
top of the script.

**macOS Shortcut:** A Shortcut with a selection menu can be built from four actions —
"Run Shell Script" (`switch-portfolio.sh --list`) → "Split Text" (on new lines)
→ "Choose from List" → "Run Shell Script" with the chosen path as argument
(`switch-portfolio.sh "$1"`). This lets you switch the portfolio by click, keyboard
shortcut, or Siri.

## Configuration (environment variables)

| Variable | Default | Meaning |
|----------|---------|-----------|
| `PP_FILE_PATH` | – | Path to the `.portfolio` file (single-source fallback, `/data/portfolio.portfolio` in the container). Ignored if `PP_PORTFOLIOS_CONFIG` is set. |
| `PP_PASSWORD` | empty | Password for encrypted files (single-source). |
| `PP_PORTFOLIOS_CONFIG` | empty | Path to the JSON configuration of multiple portfolio sources (multi-source, see above). Takes precedence over `PP_FILE_PATH`/`PP_PASSWORD`. |
| `MCP_TRANSPORT` | `streamable-http` | `stdio`, `streamable-http`, or `sse`. |
| `MCP_SERVER_PORT` | `8080` | Listening port for HTTP transports (including Docker); unused for stdio. |
| `MCP_AUTH_TOKEN` | empty | Optional bearer token; empty = no auth. **Required** as soon as the server is reachable outside a trusted local network. |
| `MCP_REQUIRE_AUTH` | `false` | For HTTP transports, the server aborts startup when this is `true` and `MCP_AUTH_TOKEN` is empty. Set to `true` in `docker-compose.yml` (production); ignored for stdio. |

## Structure

- `src/config.py` — Pydantic settings (env / `.env`).
- `src/portfolio.py` — `Portfolio` class (mtime-based cache, name↔UUID resolution,
  filtering & aggregation, one instance per source) + `PortfolioRegistry` (manages
  multiple `Portfolio` instances based on the configured sources, one per `source` id).
- `src/mcp_server.py` — FastMCP tools (thin wrappers around the registry), optional bearer auth.
- `src/price_feed.py` — SSRF-protected scraper for the `GENERIC_HTML_TABLE` price feed
  (ariva.de), used by `refresh_prices`.
- `src/main.py` — server startup.
- `src/pp_parser/` — vendored parser (decrypts/decompresses the file, reads protobuf).
