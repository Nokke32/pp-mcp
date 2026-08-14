*[English](README.md) | Deutsch*

# pp-mcp — MCP Server für Portfolio Performance

Ein read-only MCP-Server, der Konten- und Depotdaten aus einer oder mehreren
[Portfolio Performance](https://www.portfolio-performance.info/) `.portfolio`-Dateien
gefiltert bereitstellt — z.B. um daraus Reports zu erzeugen (Umsätze eines Kontos,
Ausschüttungen/Zinsen/Steuern eines Zeitraums usw.).

Dateien werden nur **gelesen**, nie verändert. Unterstützt unverschlüsselte und
AES-verschlüsselte (passwortgeschützte) Dateien. Funktioniert als Standard-[MCP](https://modelcontextprotocol.io)-Server
mit jedem MCP-kompatiblen KI-Assistenten (Claude usw.) oder eigenen Skripten.

**📖 Die vollständige Dokumentation steht im
[Wiki](https://github.com/Nokke32/pp-mcp/wiki)** — Installation (lokal & Docker,
Single- & Multi-Source), KI-Assistenten anbinden (Claude Desktop, Claude Code,
andere), Beispiel-Prompts und die komplette Tool-Referenz (Parameter/Rückgaben)
fürs direkte Scripten gegen pp-mcp.

## Schnellstart

```bash
pip install -r requirements.txt
export PP_FILE_PATH=/Pfad/zur/datei.portfolio
python -m src.main   # vom Repo-Root aus; läuft auf http://localhost:8080
```

Oder mit Docker:

```bash
cp .env.example .env
docker-compose -f docker-compose.dev.yml up -d --build
```

Details zu Docker-Produktivbetrieb/Multi-Source, allen Umgebungsvariablen und dem
Anbinden eines KI-Assistenten stehen auf der Wiki-Seite
[Installation](https://github.com/Nokke32/pp-mcp/wiki/Installation) bzw.
[Configuring AI Tools](https://github.com/Nokke32/pp-mcp/wiki/Configuring-AI-Tools).

## Begriffe

Portfolio Performance verwendet das Wort "Portfolio" für zwei verschiedene Dinge,
was zu Verwechslungen führen kann — pp-mcp verwendet deshalb überall konsistent
folgende Begriffe (Tool-Beschreibungen, Parameter, Wiki):

- **Quelle** (Parameter `source`) — eine komplette `.portfolio`-Datei, also eine
  konfigurierte Datenquelle. Siehe `list_data_sources`.
- **Depot** (Parameter `portfolio_name`) — ein Wertpapierdepot *innerhalb* einer
  Quelle (Portfolio Performance nennt dieses Objekt intern selbst "portfolio").
  Siehe `list_portfolios`.
- **Konto** (Parameter `account`) — ein Verrechnungskonto innerhalb einer Quelle.
  Siehe `list_accounts`.
- **Wertpapier** (Parameter `security`) — eine Aktie, ein Fonds, ETF usw. Siehe
  `list_securities`.

Ist im jeweiligen Kontext unklar, ob mit "Portfolio" eine Quelle oder ein Depot
gemeint ist, hilft ein Blick in `list_data_sources` und `list_portfolios`, welche
der beiden Bezeichnungen tatsächlich zutrifft.

## Aufbau

- `src/config.py` — Pydantic-Settings (Env / `.env`).
- `src/portfolio.py` — `Portfolio`-Klasse (Cache mtime-basiert, Name↔UUID-Auflösung,
  Filter & Aggregation, unverändert pro Quelle) + `PortfolioRegistry` (verwaltet mehrere
  `Portfolio`-Instanzen anhand der konfigurierten Quellen, eine pro `source`-Id).
- `src/mcp_server.py` — FastMCP-Tools (dünne Wrapper um die Registry), optionale Bearer-Auth.
- `src/price_feed.py` — SSRF-geschützter Scraper für den `GENERIC_HTML_TABLE`-Kurs-Feed
  (ariva.de), genutzt von `refresh_prices`.
- `src/main.py` — Serverstart.
- `src/pp_parser/` — vendorierter Parser (entschlüsselt/dekomprimiert die Datei, liest Protobuf).
