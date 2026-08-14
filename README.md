*English | [Deutsch](README_de.md)*

# pp-mcp — MCP Server for Portfolio Performance

A read-only MCP server that provides filtered account and portfolio data from one or
more [Portfolio Performance](https://www.portfolio-performance.info/) `.portfolio`
files — e.g. to generate reports from them (transactions of an account,
distributions/interest/taxes for a period, etc.).

Files are only **read**, never modified. Supports unencrypted and AES-encrypted
(password-protected) files. Works as a standard [MCP](https://modelcontextprotocol.io)
server with any MCP-compatible AI assistant (Claude, etc.) or your own scripts.

**📖 Full documentation is in the [Wiki](https://github.com/Nokke32/pp-mcp/wiki)**
— installation (local & Docker, single- & multi-source), connecting AI assistants
(Claude Desktop, Claude Code, others), example prompts, and the complete tool
reference (parameters/return values) for scripting against pp-mcp directly.

## Quick start

```bash
pip install -r requirements.txt
export PP_FILE_PATH=/path/to/file.portfolio
python -m src.main   # from the repo root; runs on http://localhost:8080
```

Or with Docker:

```bash
cp .env.example .env
docker-compose -f docker-compose.dev.yml up -d --build
```

See the [Installation](https://github.com/Nokke32/pp-mcp/wiki/Installation) wiki
page for the production/multi-source Docker setup, all environment variables, and
connecting an AI assistant
([Configuring AI Tools](https://github.com/Nokke32/pp-mcp/wiki/Configuring-AI-Tools)).

## Terminology

Portfolio Performance uses the word "portfolio" for two different things, which can
be ambiguous — pp-mcp uses these terms consistently everywhere (tool descriptions,
parameters, the wiki):

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
