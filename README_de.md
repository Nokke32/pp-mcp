*[English](README.md) | Deutsch*

# pp-mcp — MCP Server für Portfolio Performance

Ein read-only MCP-Server, der Konten- und Depotdaten aus einer oder mehreren
[Portfolio Performance](https://www.portfolio-performance.info/) `.portfolio`-Dateien
gefiltert bereitstellt — z.B. um daraus Reports zu erzeugen (Umsätze eines Kontos,
Ausschüttungen/Zinsen/Steuern eines Zeitraums usw.).

Dateien werden nur **gelesen**, nie verändert. Unterstützt unverschlüsselte und
AES-verschlüsselte (passwortgeschützte) Dateien.

## Mehrere Portfolio-Dateien (Multi-Source)

Standardmäßig bedient eine Instanz genau eine Datei (`PP_FILE_PATH`). Über
`PP_PORTFOLIOS_CONFIG` lässt sich stattdessen eine JSON-Datei mit mehreren Quellen
konfigurieren (siehe `portfolios.json.example`):

```json
[
  {"id": "example1", "label": "Example1", "path": "/data/portfolios/Example1.portfolio", "password": null},
  {"id": "example2", "label": "Example2", "path": "/data/portfolios/Example2.portfolio", "password": null}
]
```

Jedes Tool bekommt dann einen zusätzlichen optionalen Parameter `source` (die `id`
aus der Config). Bei genau einer konfigurierten Quelle kann `source` weggelassen
werden. `list_data_sources` gibt die verfügbaren `id`+`label` zurück, ohne Pfade
oder Passwörter preiszugeben. Jede Quelle hat ihren eigenen mtime-Cache.

## Tools

| Tool | Zweck |
|------|-------|
| `list_data_sources` | Konfigurierte Portfolio-Quellen (id, label) für den `source`-Parameter der übrigen Tools. |
| `get_file_info` | Metadaten der Datei: Pfad, Änderungsdatum, verschlüsselt ja/nein, Version, Basiswährung, Anzahl Konten/Depots/Wertpapiere/Transaktionen, frühestes/spätestes Transaktionsdatum. |
| `list_accounts` | Alle Konten (uuid, name, currencyCode, isRetired). |
| `list_portfolios` | Alle Depots (uuid, name, Referenzkonto, isRetired). |
| `list_securities` | Alle Wertpapiere (uuid, name, isin, wkn, tickerSymbol, currencyCode, isRetired). |
| `list_transaction_types` | Gültige Transaktionsarten als Filter-Hilfe. |
| `get_transactions` | Gefilterte Transaktionen (Zeitraum, Arten, Konto/Depot/Wertpapier – jeweils optional), inkl. `securityIsin` je Transaktion. |
| `get_transaction_summary` | Summen und Anzahl je Transaktionsart + Gesamtsumme im Zeitraum. |
| `get_latest_price` | Aktuellster bekannter Kurs eines Wertpapiers (latest-Feld, sonst jüngster Historien-Kurs). |
| `get_price_history` | Historische Tagesschlusskurse im Zeitraum (optional `limit` für die letzten N). |
| `get_price_on` | Kurs zu einem Stichtag – exakt oder letzter Kurs davor (für Stichtagsbewertungen). |
| `list_latest_prices` | Aktuellster Kurs **aller** Wertpapiere als Übersicht. |
| `list_price_feeds` | Kurs-Update-Konfiguration (Feed-Typ + Feed-URL) aller aktiven Wertpapiere. |
| `refresh_prices` | Fehlende, aktuellere Kurse per Feed nachladen – nur temporär im Speicher, siehe unten. |
| `get_holdings` | Depotbewertung: Bestände (Stückzahl × Kurs) zu einem Stichtag, optional je Depot. |
| `get_holdings_history` | Wertverlauf des Depots über mehrere Stichtage (`daily`/`weekly`/`monthly`) – Summen je Währung, für Charts. |
| `get_unrealized_gains` | Unrealisierter Kurserfolg je offener Position (gleitender Durchschnittspreis, wie PP-Standard). |
| `get_realized_gains` | Realisierter Kurserfolg je Wertpapier aus Verkäufen im Zeitraum. |
| `get_account_balance` | Kontostand (Saldo) eines Verrechnungskontos zu einem Stichtag. |
| `list_taxonomies` | Alle Taxonomien (Anlagekategorien, Regionen, Branchen, …) mit Klassifikationsbaum und Zuweisungen. |
| `get_asset_allocation` | Bestandswert verteilt auf die Klassifikationen einer Taxonomie. |
| `list_investment_plans` | Sparpläne/Investmentpläne mit Wertpapier/Depot/Konto, Betrag und Intervall. |
| `ping` | Prüft, ob der Server läuft. |

`get_transactions` deckt beide Kern-Anwendungsfälle ab:
- **Umsätze eines Kontos im Zeitraum**: `account` + `date_from`/`date_to` setzen.
- **Depottransaktionen bestimmter Arten**: `portfolio_name` + `types` (+ Zeitraum) setzen.

**Für den aktuellen Kontostand `get_account_balance` verwenden, nicht `get_transactions`
manuell aufsummieren:** `get_transactions`/`get_transaction_summary` filtern nur nach dem
in der Transaktion primär referenzierten Konto – bei `CASH_TRANSFER` zwischen zwei Konten
taucht der Zufluss beim Zielkonto dort **nicht** auf (nur beim Quellkonto). `get_account_balance`
berücksichtigt beide Seiten von `CASH_TRANSFER` sowie die korrekten Vorzeichen aller
kontobewegenden Transaktionsarten und liefert den tatsächlichen Saldo.

Konto/Depot/Wertpapier können als **Name oder UUID** angegeben werden (Groß-/Kleinschreibung egal).
Datumsangaben im ISO-Format `YYYY-MM-DD`. Beträge werden als Strings zurückgegeben (exakte Dezimalwerte).
Alle Tools außer `list_transaction_types` (quellenunabhängig) und `list_data_sources`
akzeptieren zusätzlich `source` zur Auswahl der Portfolio-Datei bei Multi-Source-Betrieb.

Transaktionsarten: `PURCHASE, SALE, SECURITY_TRANSFER, CASH_TRANSFER, DEPOSIT, REMOVAL,
DIVIDEND, INTEREST, INTEREST_CHARGE, TAX, TAX_REFUND, FEE, FEE_REFUND`.

Bei den Kurs-Tools kann das Wertpapier zusätzlich über **ISIN, WKN oder Ticker** (statt
Name/UUID) angegeben werden. Kurse werden als Strings zurückgegeben; `source` unterscheidet
`latest` (zuletzt abgerufener Kurs) von `historical` (jüngster Historien-Schlusskurs).

`get_holdings` berechnet die gehaltene Stückzahl je Wertpapier aus den Transaktionen
(PURCHASE/SALE, Ein-/Auslieferungen, Depotüberträge) und bewertet sie mit dem Kurs zum
Stichtag. Ohne `portfolio_name` werden alle Depots zusammengefasst (Überträge zwischen
Depots heben sich auf), ohne `date` gilt der aktuellste Kurs. **Keine Währungsumrechnung:**
Werte stehen in der Währung des Wertpapiers, Summen werden je Währung ausgewiesen
(`totalsByCurrency`).

`get_holdings_history` wiederholt dieselbe Berechnung für eine Serie von Stichtagen
zwischen `date_from` und `date_to` (inklusive) und liefert je Stichtag nur
`totalsByCurrency` (keine Einzelpositionen) – gedacht für Wertverlauf-Charts. Ohne
`date_from` wird das Datum der ersten Transaktion verwendet, ohne `date_to` das
heutige Datum. `interval` steuert die Auflösung: `monthly` (Standard, Monatsend-
Stichtage, letzter Punkt ist immer `date_to`), `weekly` oder `daily`.

## Fehlende Kurse nachladen (`refresh_prices`)

Portfolio Performance konfiguriert Wertpapiere mit einem Kurs-Feed (`feed`/`feedURL`
je Security, sichtbar über `list_price_feeds`). Ist die `.portfolio`-Datei nicht ganz
aktuell (PP wurde z.B. länger nicht geöffnet), kann `refresh_prices` fehlende, neuere
Kurse direkt über diesen Feed nachladen. Aktuell wird dafür nur der Feed-Typ
`GENERIC_HTML_TABLE` mit `ariva.de`-Host unterstützt (SSRF-geschützt: nur `https`,
Host-Allowlist, keine privaten/internen IPs) – andere Feeds (`PP`, `YAHOO`, …) werden
übersprungen und als solche gemeldet, nicht als Fehler.

Die nachgeladenen Kurse landen in einem **rein temporären In-Memory-Overlay** je
Portfolio-Quelle – die `.portfolio`-Datei wird dabei **nie** verändert. Der Overlay
ergänzt nur Datumswerte, die in der Datei fehlen (bestehende Datei-Kurse werden nie
überschrieben), und wird automatisch von allen Preis-/Bewertungs-Tools mitberück-
sichtigt (`get_latest_price`, `get_price_history`, `get_holdings`,
`get_unrealized_gains`, `get_holdings_history`, …). Er wird verworfen, sobald die
Datei tatsächlich neu geschrieben wird (mtime-Änderung, z.B. durch PP selbst) oder
der Server neu startet – ein erneuter `refresh_prices`-Aufruf holt ihn bei Bedarf
wieder auf den aktuellen Stand.

## Betrieb mit Docker (empfohlen)

Zwei Compose-Dateien für unterschiedliche Einsatzszenarien:

- **`docker-compose.yml`** — Multi-Source-Produktivbetrieb (z.B. Synology NAS):
  Verzeichnis mit mehreren `.portfolio`-Dateien + `portfolios.json`, `MCP_AUTH_TOKEN`
  Pflicht, Port nur auf `127.0.0.1` gebunden, externe Docker-Netzwerke für
  nginx-proxy-manager und weitere Backends.
- **`docker-compose.dev.yml`** — einfacher lokaler Single-Source-Betrieb: eine
  einzelne Datei über `PP_HOST_FILE` gemountet, ohne Auth-Pflicht, ohne externe
  Netzwerke.

```bash
cp .env.example .env      # anpassen je nach gewählter Compose-Datei
docker-compose -f docker-compose.dev.yml up -d --build   # lokal, Single-Source
# oder
docker-compose up -d --build                             # Produktiv, Multi-Source
```

Der MCP-Server läuft auf `http://localhost:8080` (streamable-http). Details zu den
jeweiligen Umgebungsvariablen siehe Kommentare in der jeweiligen Compose-Datei sowie
`portfolios.json.example`.

## Lokaler Betrieb (ohne Docker)

```bash
pip install -r requirements.txt
export PP_FILE_PATH=/Pfad/zur/datei.portfolio
# optional: export PP_PASSWORD=... ; export MCP_TRANSPORT=streamable-http
python src/main.py
```

Für Multi-Source stattdessen `PP_PORTFOLIOS_CONFIG=/Pfad/zur/portfolios.json` setzen
(hat Vorrang vor `PP_FILE_PATH`/`PP_PASSWORD`).

## In Claude einrichten

`pp-mcp` spricht `streamable-http`, nicht stdio, wird also als entfernter HTTP-MCP-
Server eingerichtet. Der Endpunkt ist `http://<host>:<port>/mcp` (`/sse` bei
`MCP_TRANSPORT=sse`).
(Siehe [unten](#andere-mcp-clientski-assistenten-verwenden) für andere MCP-Clients/KI-Assistenten.)

**Claude Code** — per CLI:

```bash
claude mcp add --transport http pp-mcp http://localhost:8080/mcp \
  --header "Authorization: Bearer <MCP_AUTH_TOKEN>"
```

`--header` weglassen, wenn `MCP_AUTH_TOKEN` leer ist. Das schreibt in `~/.claude.json`
(User-Scope) bzw. mit `--scope project` in `.mcp.json` im aktuellen Projekt. Alternativ
die Datei direkt bearbeiten:

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

Ohne Auth-Token den `headers`-Block einfach ganz weglassen.

**Claude Desktop** startet aktuell nur lokale stdio-Server, keine entfernten
`streamable-http`-Server direkt — dafür `pp-mcp` über eine stdio-zu-HTTP-Bridge wie
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote) einbinden. Die Konfigurationsdatei
liegt unter:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

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

## Andere MCP-Clients/KI-Assistenten verwenden

`pp-mcp` ist nicht auf Claude beschränkt — es ist ein Standard-MCP-Server, der den
`streamable-http`-Transport mit gewöhnlichen MCP-Tool-Definitionen spricht. Jeder
MCP-kompatible Client bzw. KI-Assistent, der entfernte HTTP-MCP-Server unterstützt
(z.B. andere LLM-Chat-Apps, IDE-Integrationen, Agent-Frameworks), kann ihn genauso
nutzen. Den Client auf `http://<host>:<port>/mcp` zeigen lassen und, falls
`MCP_AUTH_TOKEN` gesetzt ist, den HTTP-Header `Authorization: Bearer <MCP_AUTH_TOKEN>`
mitgeben — in der Doku des jeweiligen Clients nachsehen, wie er entfernte MCP-Server
einrichtet (manche, wie Claude Desktop oben, starten direkt nur lokale stdio-Server
und brauchen eine stdio-zu-HTTP-Bridge wie `mcp-remote`).

## Portfolio-Datei umschalten (macOS)

Wer mehrere `.portfolio`-Dateien verwaltet, kann mit `switch-portfolio.sh` schnell
zwischen ihnen wechseln. Das Skript setzt `PP_FILE_PATH` in der `.env` und startet den
Server neu — bei lokalem Betrieb über den launchd-Dienst `de.pp-mcp.server`:

```bash
./switch-portfolio.sh --list                                   # aktive Dateien anzeigen
./switch-portfolio.sh /Users/du/Portfolios/Depot.portfolio     # umschalten + Neustart
```

`--list` blendet Backups (`*.backup*`) und Konflikt-Kopien (`*conflicted*`) aus.
Die Pfade (`APP_DIR`, `PORTFOLIO_DIR`, `SERVICE`) stehen als Konstanten oben im Skript.

**macOS-Kurzbefehl:** Ein Kurzbefehl mit Auswahlmenü lässt sich in vier Aktionen bauen —
„Shell-Skript ausführen" (`switch-portfolio.sh --list`) → „Text teilen" (bei Neue Zeilen)
→ „Aus Liste auswählen" → „Shell-Skript ausführen" mit dem gewählten Pfad als Argument
(`switch-portfolio.sh "$1"`). So wird das Depot per Klick, Tastenkürzel oder Siri gewechselt.

## Konfiguration (Umgebungsvariablen)

| Variable | Default | Bedeutung |
|----------|---------|-----------|
| `PP_FILE_PATH` | – | Pfad zur `.portfolio`-Datei (Single-Source-Fallback, im Container `/data/portfolio.portfolio`). Ignoriert, wenn `PP_PORTFOLIOS_CONFIG` gesetzt ist. |
| `PP_PASSWORD` | leer | Passwort für verschlüsselte Dateien (Single-Source). |
| `PP_PORTFOLIOS_CONFIG` | leer | Pfad zur JSON-Konfiguration mehrerer Portfolio-Quellen (Multi-Source, siehe oben). Hat Vorrang vor `PP_FILE_PATH`/`PP_PASSWORD`. |
| `MCP_TRANSPORT` | `streamable-http` | `streamable-http` oder `sse`. |
| `MCP_SERVER_PORT` | `8080` | Host-Port (Docker). |
| `MCP_AUTH_TOKEN` | leer | Optionaler Bearer-Token; leer = keine Auth. **Pflicht**, sobald der Server außerhalb eines vertrauenswürdigen lokalen Netzes erreichbar ist. |
| `MCP_REQUIRE_AUTH` | `false` | Bei `true` bricht der Server-Start ab, wenn `MCP_AUTH_TOKEN` leer ist – zusätzliche Absicherung gegen versehentlichen ungeschützten Betrieb, unabhängig von Docker/Compose. In `docker-compose.yml` (Produktivbetrieb) auf `true` gesetzt. |

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
