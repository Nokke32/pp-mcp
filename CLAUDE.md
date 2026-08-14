# CLAUDE.md

Hinweise für Claude Code beim Arbeiten in diesem Repository.

## Überblick

`pp-mcp` ist ein **read-only** MCP-Server, der Konten- und Depotdaten aus einer oder
mehreren Portfolio-Performance-`.portfolio`-Dateien gefiltert bereitstellt (für Reports).
Ein einzelner Python-Prozess, nur MCP – **keine Web-UI, keine Datenbank, keine Auth**
(außer optionalem Bearer-Token). Tool-Beschreibungen, Docstrings und Kommentare in
`src/mcp_server.py` sind auf Englisch (öffentlicher MCP-Server, internationale Nutzer/
LLMs). Diese CLAUDE.md und Commit-Messages bleiben auf Deutsch (Arbeitssprache des Maintainers).

`pp-mcp` ist als **einzige Quelle der Wahrheit** für Portfolio-Performance-Daten
gedacht: andere Anwendungen (z.B. DividendenTracker, ein künftiges Analyse-Dashboard)
sollen ausschließlich über diesen Server auf `.portfolio`-Dateien zugreifen und sie
nicht selbst parsen. Produktivbetrieb: NAS im lokalen Netz, intern im Docker-Netz
(nicht öffentlich exponiert, außer über einen Reverse-Proxy unter einer festen
internen Domain), zusätzlich per `MCP_AUTH_TOKEN` geschützt.

**Dokumentation:** Seit 2026-08-14 ist die ausführliche Doku (Installation,
KI-Tool-Konfiguration, Beispiel-Prompts, vollständige Tool-Referenz, Beispiel-Skripte)
im Wiki, nicht mehr in der README. Zwei gespiegelte Wikis: Gitea (primäre Quelle,
intern gehostet, lokaler Klon unter `~/Coding/MCP/pp-mcp.wiki`) und GitHub
(`https://github.com/Nokke32/pp-mcp/wiki`, Branch `master` statt `main`). README.md/
README_de.md sind auf ein Minimum reduziert (Kurzbeschreibung, Quick-Start, Begriffe,
Struktur) und verlinken je nach Remote auf das jeweils passende Wiki (Gitea ist nur
intern erreichbar, daher zwei unterschiedliche Link-Ziele in den sonst identischen
READMEs).

## Betrieb & Entwicklung

Gedacht für Docker, läuft aber auch lokal. `docker-compose.yml` ist der
Multi-Source-Produktivbetrieb (NAS im lokalen Netz, `MCP_AUTH_TOKEN` Pflicht);
`docker-compose.dev.yml` der einfache lokale Single-Source-Betrieb
(`docker-compose -f docker-compose.dev.yml up -d --build`):

```bash
pip install -r requirements.txt
export PP_FILE_PATH=/Pfad/zur/datei.portfolio
python -m src.main         # MCP-Server auf :8080 (streamable-http); vom Repo-Root
                            # aus ("python src/main.py" schlägt fehl: ModuleNotFoundError)
```

Kein Test-Framework/Linter/CI. „Testen" = Tools gegen eine echte `.portfolio`-Datei
aufrufen. Es gibt einen `ping`-Tool und einen TCP-Healthcheck auf Port 8080.

Aktuell läuft der Server lokal **ohne Docker** als launchd-Dienst
(`~/Library/LaunchAgents/de.pp-mcp.server.plist`, `KeepAlive=true`), deployt nach
`~/Applications/pp-mcp` (eigene Kopie, nicht dieses Repo). `switch-portfolio.sh`
schaltet die aktive `.portfolio`-Datei um: `PP_FILE_PATH` in der deployten `.env` ändern und
den Dienst per `launchctl kickstart -k gui/$UID/de.pp-mcp.server` neu starten (nötig, weil
`PP_FILE_PATH` nur beim Prozessstart gelesen wird).

```bash
./switch-portfolio.sh --list                                # aktive Dateien anzeigen
./switch-portfolio.sh ~/Portfolios/Depot.portfolio                # umschalten + Neustart
```

`--list` blendet Backups (`*.backup*`) und Konflikt-Kopien (`*conflicted*`) aus; Pfade
(`APP_DIR`, `PORTFOLIO_DIR`, `SERVICE`) stehen als Konstanten oben im Skript. Ein
macOS-Kurzbefehl mit Auswahlmenü besteht aus vier Aktionen — „Shell-Skript ausführen"
(`switch-portfolio.sh --list`) → „Text teilen" (bei Neue Zeilen) → „Aus Liste
auswählen" → „Shell-Skript ausführen" mit dem gewählten Pfad als Argument
(`switch-portfolio.sh "$1"`). Diese Details stehen bewusst nur hier (personenbezogener
Deploy, nicht Teil der öffentlichen Doku) und nicht mehr in README/Wiki.

## Architektur

- **`src/config.py`** — Pydantic-Settings aus Env/`.env`: `PP_FILE_PATH`/`PP_PASSWORD`
  (Single-Source-Fallback), `PP_PORTFOLIOS_CONFIG` (Pfad zu einer JSON-Datei mit
  mehreren Quellen `[{id, label, path, password}]`, hat Vorrang vor `PP_FILE_PATH`),
  `MCP_TRANSPORT`/`MCP_SERVER_HOST`/`MCP_SERVER_PORT`, `MCP_AUTH_TOKEN`.
  Container-Port ist fest 8080. `MCP_SERVER_HOST` default ist `127.0.0.1`
  (geringste Angriffsfläche für lokalen/Nicht-Docker-Betrieb); beide
  `docker-compose*.yml` setzen es explizit auf `0.0.0.0`, sonst wäre der
  Container über das Port-Mapping/das nginx-Netz nicht erreichbar.
  `MCP_TRANSPORT=stdio` läuft ohne residenten HTTP-Server (Client startet `pp-mcp`
  selbst als Subprozess) – dabei entfallen ASGI-App/Bearer-Auth komplett, da keine
  HTTP-Schicht existiert; gedacht für Clients, die MCP-Server als Subprozess starten
  (z.B. Claude Desktop direkt, ohne `mcp-remote`-Bridge), nicht für den
  Docker/NAS-Betrieb.
- **`src/portfolio.py`** — Herzstück. `Portfolio`-Klasse mit **mtime-Cache**
  (`_ensure_loaded` parst nur neu, wenn sich `getmtime` ändert). UUID↔Name-Lookups,
  `_resolve` (Name *oder* UUID, case-insensitiv), Anreicherung der Transaktionen mit
  `accountName`/`portfolioName`/`securityName`/`securityIsin`, `filter_transactions`,
  `summarize`.
  Kurse: `_find_security` (Name/ISIN/WKN/Ticker/UUID), `latest_price`, `price_history`,
  `price_on`, `list_latest_prices`. `_find_security` wird auch von `unrealized_gains`/
  `realized_gains` genutzt, um deren optionalen `security`-Parameter aufzulösen (analog
  zum bestehenden `security`-Parameter bei `get_transactions`/`get_price_history`) — ohne
  `security` liefern beide wie bisher alle Positionen. Bewertung: `holdings` (Bestand × Kurs zum Stichtag) über
  `_share_balances` (PURCHASE/SALE/Ein-/Auslieferung ±, `SECURITY_TRANSFER` Quelle−/Ziel+;
  ohne Depot-Filter heben sich Überträge auf) und `_price_asof`. `holdings_history`
  wiederholt dieselbe Bewertung für eine Serie von Stichtagen (`_sample_dates`:
  `daily`/`weekly`/`monthly`, monatlich = Monatsende, letzter Punkt immer `date_to`) und
  liefert nur `totalsByCurrency` je Stichtag (für Wertverlauf-Charts). Keine FX-Umrechnung –
  Summen je Währung. Dafür liest der Parser `otherPortfolioUuid` (Transfer-Ziel) und
  `otherAccountUuid` (Konto-Transfer-Ziel). Kontostand: `account_balance` summiert alle
  kontobewegenden Transaktionsarten (`_CASH_SIGN`: DEPOSIT/REMOVAL/DIVIDEND/INTEREST/
  INTEREST_CHARGE/TAX/TAX_REFUND/FEE/FEE_REFUND/PURCHASE/SALE) mit festem Vorzeichen;
  `CASH_TRANSFER` gesondert (Quelle `accountUuid` −, Ziel `otherAccountUuid` +) – **wichtig:**
  `get_transactions`/`summarize` filtern nur nach `accountUuid` und zeigen daher beim
  Zielkonto eines `CASH_TRANSFER` nichts an; nur `account_balance` berücksichtigt beide Seiten.
  Taxonomien: `list_taxonomies` gibt die von PP mitgelieferten Klassifikationsbäume
  (Anlagekategorien, Regionen, Branchen, …) mit Zuweisungen roh zurück; `asset_allocation`
  verteilt den `holdings`-Bestandswert (plus, ohne Depot-Filter, zugewiesene
  `account_balance`-Kontostände, z.B. für "Barvermögen") gemäß `assignment.weight` (Skala
  0..10000) auf die Klassifikationen einer Taxonomie, unzugeordnete Wertpapiere/Konten
  landen unter „Nicht klassifiziert". `_resolve_taxonomy` löst Name/UUID auf, ohne Angabe nur
  zulässig bei genau einer Taxonomie. Sparpläne: `investment_plans` listet `PInvestmentPlan`
  roh mit aufgelösten Namen (kein Berechnungslogik, nur Durchreichen). Der Parser liest
  `client.taxonomies`/`client.plans` zusätzlich zu den bisherigen Feldern; einzelne Felder
  darin haben in der Protobuf-Definition keine Presence-Tracking (`color`, `parentId`,
  `PInvestmentPlan.date`) und dürfen daher nicht per `HasField` geprüft werden.
  `_serialize` macht Decimal→str und Datum→ISO-String (JSON-sicher). Transaktionstypen
  in `TRANSACTION_TYPES`. `Portfolio`-Instanzen sind seit dem Multi-Source-Umbau nicht
  mehr direkt global, sondern werden von **`PortfolioRegistry`** verwaltet: eine
  Instanz pro konfigurierter Quelle (`_load_sources()` liest entweder
  `PP_PORTFOLIOS_CONFIG` oder baut eine einzige Quelle `"default"` aus
  `PP_FILE_PATH`/`PP_PASSWORD`). `registry.get(source_id)` liefert die passende
  `Portfolio`-Instanz; `source_id` ist optional, solange nur eine Quelle konfiguriert
  ist, sonst Pflicht (sonst `ValueError`). Globale Instanz `registry`.
- **`src/mcp_server.py`** — `FastMCP` (aus `mcp`) mit `@app.tool(...)`. Tools sind
  dünne Wrapper um `registry.get(source)...`; jedes Tool (außer `list_transaction_types`
  und `list_data_sources`) hat einen optionalen `source`-Parameter zur Auswahl der
  Portfolio-Quelle. `list_data_sources` gibt die konfigurierten `id`+`label` zurück
  (ohne Pfade/Passwörter). Fehler werden **nicht geworfen**, sondern als
  `{"status": "error", "message": ...}` zurückgegeben. `build_mcp_asgi_app(transport)`
  baut die Starlette-App und hängt bei gesetztem `MCP_AUTH_TOKEN` die
  `BearerAuthMiddleware` (rohe ASGI, damit SSE-Streams nicht gepuffert werden) davor.
- **`src/main.py`** — startet nur den MCP-Server via `uvicorn.run(build_mcp_asgi_app(...))`.
- **`src/pp_parser/`** — **vendorierter** Parser (kopiert aus
  `DividendenTracker/pp_parser`). `parse_portfolio_file(filepath, password) -> dict`
  entschlüsselt (AES), dekomprimiert (ZIP) und liest die Protobuf-Daten. Bei Änderungen
  am Original-Parser hier manuell nachziehen. **Abweichung von upstream:** Kurse (Quotes)
  werden mit `QUOTE_FACTOR = 10^8` skaliert (upstream teilte fälschlich durch `100`), und das
  `latest`-Feld (aktuellster Kurs mit high/low/volume) wird zusätzlich ausgelesen. Jedes
  Security-Dict hat daher `prices` (Liste `{date, close}`) und `latest` (`{date, close, high,
  low, volume}` oder `None`).

## Wichtige Details

- Die `.portfolio`-Datei(en) werden im Compose **read-only** gemountet (`:ro`);
  Single-Source über `PP_HOST_FILE` → `PP_FILE_PATH=/data/portfolio.portfolio`
  (siehe `docker-compose.dev.yml`), Multi-Source über ein Verzeichnis-Mount +
  `portfolios.json` → `PP_PORTFOLIOS_CONFIG` (siehe `docker-compose.yml` und
  `portfolios.json.example`).
- Beträge kommen als **Strings** aus den Tools (exakte Decimals). Datumsfilter im
  Tool sind ISO `YYYY-MM-DD`, Zeitraum ist **inklusive** beider Grenzen.
- `get_transactions` hat den Depot-Parameter `portfolio_name` (nicht `portfolio`),
  um Namenskollisionen mit dem Modul `portfolio` zu vermeiden.
- Namenskollision bewusst vermieden: `list_portfolios` listet Depots *innerhalb*
  einer Datei; `list_data_sources` listet die konfigurierten Portfolio-*Dateien*.
