"""MCP-Server für Portfolio Performance.

Stellt lesende Tools bereit, um gefilterte Konten- und Depotdaten aus einer
Portfolio-Performance-Datei abzufragen und daraus Reports zu erstellen.

Alle Tools sind dünne Wrapper um `src.portfolio`. Fehler werden nicht geworfen,
sondern als `{"status": "error", "message": ...}` zurückgegeben (Konvention wie mail-mcp).
"""
import hmac
import logging
from typing import List, Dict, Optional, Any

from mcp.server import FastMCP

from src.config import settings
from src.portfolio import registry, TRANSACTION_TYPES

_SOURCE_DOC = (
    " Optional: 'source' wählt die Portfolio-Quelle (id aus list_data_sources) bei "
    "mehreren konfigurierten Dateien; bei genau einer Quelle kann sie weggelassen werden."
)

logger = logging.getLogger(__name__)

app = FastMCP(
    name="pp-mcp-server",
    host=settings.MCP_SERVER_HOST,
    port=settings.MCP_SERVER_PORT,
    instructions=(
        "MCP Server für Portfolio Performance. Liefert gefilterte Konten- und "
        "Depotdaten (Umsätze, Transaktionen nach Art/Zeitraum) für Reports. "
        f"Version {settings.APP_VERSION}"
    ),
)


def _error(e: Exception) -> Dict[str, Any]:
    """Wandelt eine Exception in eine Client-Antwort um.

    Bei FileNotFoundError wird der volle Server-Dateipfad NICHT an den Client
    weitergegeben (Informationsleck über die Serverumgebung) – nur ins Log.
    """
    logger.error(f"Fehler: {e}")
    if isinstance(e, FileNotFoundError):
        return {
            "status": "error",
            "message": "Portfolio-Datei nicht gefunden oder nicht lesbar (siehe Server-Log).",
        }
    return {"status": "error", "message": str(e)}


# ==================== Datei / Stammdaten ====================

@app.tool(
    description="Konfigurierte Portfolio-Quellen (id + label) für den 'source'-Parameter "
                "der übrigen Tools. Bei genau einer konfigurierten Quelle ist 'source' "
                "überall optional."
)
def list_data_sources() -> Any:
    """Konfigurierte Portfolio-Quellen (ohne Pfade/Passwörter)."""
    return registry.list_sources()


@app.tool(
    description="Informationen zur Portfolio-Datei: Pfad, Änderungsdatum, "
                "verschlüsselt ja/nein, Version, Basiswährung, Anzahl Konten/Depots/"
                "Wertpapiere/Transaktionen sowie frühestes/spätestes Transaktionsdatum."
                + _SOURCE_DOC
)
def get_file_info(source: Optional[str] = None) -> Dict[str, Any]:
    """Metadaten und Kennzahlen zur Portfolio-Datei."""
    try:
        return registry.get(source).file_info()
    except Exception as e:
        return _error(e)


@app.tool(
    description="Alle Konten (Verrechnungs-/Geldkonten) mit uuid, name, currencyCode und "
                "isRetired." + _SOURCE_DOC
)
def list_accounts(source: Optional[str] = None) -> Any:
    """Liste aller Konten."""
    try:
        return registry.get(source).list_accounts()
    except Exception as e:
        return _error(e)


@app.tool(
    description="Alle Depots (Portfolios) mit uuid, name, Referenzkonto und isRetired."
                + _SOURCE_DOC
)
def list_portfolios(source: Optional[str] = None) -> Any:
    """Liste aller Depots."""
    try:
        return registry.get(source).list_portfolios()
    except Exception as e:
        return _error(e)


@app.tool(
    description="Alle Wertpapiere mit uuid, name, isin, wkn, tickerSymbol, currencyCode und "
                "isRetired (in PP als inaktiv markiert)." + _SOURCE_DOC
)
def list_securities(source: Optional[str] = None) -> Any:
    """Liste aller Wertpapiere."""
    try:
        return registry.get(source).list_securities()
    except Exception as e:
        return _error(e)


@app.tool(
    description="Liste der gültigen Transaktionsarten als Filter-Hilfe "
                "(z.B. DIVIDEND, INTEREST, TAX, PURCHASE, SALE, DEPOSIT, REMOVAL, FEE)."
)
def list_transaction_types() -> List[str]:
    """Verfügbare Transaktionsarten (quellenunabhängig)."""
    return TRANSACTION_TYPES


# ==================== Kurse ====================

@app.tool(
    description="Aktuellster bekannter Kurs eines Wertpapiers. Nutzt den zuletzt "
                "abgerufenen Kurs (latest), sonst den jüngsten Historien-Schlusskurs. "
                "Wertpapier als Name, ISIN, WKN, Ticker oder UUID. Kurs als String "
                "(exakter Dezimalwert), Datum ISO YYYY-MM-DD, 'source' = latest|historical."
                + _SOURCE_DOC
)
def get_latest_price(security: str, source: Optional[str] = None) -> Any:
    """Aktuellster Kurs eines Wertpapiers.

    Args:
        security: Wertpapier als Name, ISIN, WKN, Ticker oder UUID.
    """
    try:
        return registry.get(source).latest_price(security)
    except Exception as e:
        return _error(e)


@app.tool(
    description="Historische Tagesschlusskurse eines Wertpapiers im Zeitraum (Grenzen "
                "inklusive), nach Datum sortiert. Wertpapier als Name, ISIN, WKN, Ticker "
                "oder UUID. Ohne Zeitraum werden ALLE Kurse geliefert (können mehrere "
                "tausend sein) – mit limit nur die letzten N. Kurse als Strings."
                + _SOURCE_DOC
)
def get_price_history(
    security: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: Optional[int] = None,
    source: Optional[str] = None,
) -> Any:
    """Historische Schlusskurse im Zeitraum.

    Args:
        security: Wertpapier als Name, ISIN, WKN, Ticker oder UUID.
        date_from: Startdatum inklusive, ISO-Format YYYY-MM-DD.
        date_to: Enddatum inklusive, ISO-Format YYYY-MM-DD.
        limit: Nur die letzten N Kurse des Zeitraums zurückgeben.
    """
    try:
        return registry.get(source).price_history(
            security, date_from=date_from, date_to=date_to, limit=limit
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Kurs eines Wertpapiers zu einem Stichtag. Gibt es keinen Kurs am Tag "
                "selbst, wird der letzte Kurs davor geliefert (exact=false). Nützlich für "
                "Stichtagsbewertungen (z.B. Jahresende). Wertpapier als Name, ISIN, WKN, "
                "Ticker oder UUID; Datum ISO YYYY-MM-DD." + _SOURCE_DOC
)
def get_price_on(security: str, date: str, source: Optional[str] = None) -> Any:
    """Kurs zum Stichtag (exakt oder letzter davor).

    Args:
        security: Wertpapier als Name, ISIN, WKN, Ticker oder UUID.
        date: Stichtag, ISO-Format YYYY-MM-DD.
    """
    try:
        return registry.get(source).price_on(security, date)
    except Exception as e:
        return _error(e)


@app.tool(
    description="Aktuellster Kurs ALLER Wertpapiere als Übersicht (uuid, name, isin, wkn, "
                "tickerSymbol, currencyCode, date, close, source). Für Depot-Reports über "
                "alle Positionen. Kurse als Strings." + _SOURCE_DOC
)
def list_latest_prices(source: Optional[str] = None) -> Any:
    """Aktuellster Kurs aller Wertpapiere."""
    try:
        return registry.get(source).list_latest_prices()
    except Exception as e:
        return _error(e)


@app.tool(
    description="Kurs-Update-Konfiguration (Feed-Typ + Feed-URL, historisch und 'latest') "
                "aller AKTIVEN Wertpapiere (isRetired=false). Nützlich, um zu sehen, über "
                "welchen externen Feed (z.B. ariva.de) ein Wertpapier seine Kurse bezieht, "
                "bevor man refresh_prices aufruft." + _SOURCE_DOC
)
def list_price_feeds(source: Optional[str] = None) -> Any:
    """Kurs-Update-Konfiguration aller aktiven Wertpapiere."""
    try:
        return registry.get(source).list_price_feeds()
    except Exception as e:
        return _error(e)


@app.tool(
    description="Ruft über den in der Portfolio-Datei konfigurierten Kurs-Feed fehlende, "
                "aktuellere Kurse ab und hält sie NUR TEMPORÄR im Arbeitsspeicher vor "
                "(kein Schreibzugriff auf die .portfolio-Datei) – anschließend liefern "
                "get_latest_price/get_price_history/get_holdings/get_unrealized_gains "
                "diese Kurse automatisch mit. Aktuell wird nur der Feed-Typ "
                "GENERIC_HTML_TABLE mit ariva.de-Host unterstützt; andere Feeds (z.B. PP, "
                "YAHOO) werden übersprungen (skipped), nicht als Fehler gewertet. Ohne "
                "'security' werden alle aktiven Wertpapiere aktualisiert. Der Overlay wird "
                "verworfen, sobald die Datei neu geladen wird (Änderung erkannt) oder der "
                "Server neu startet." + _SOURCE_DOC
)
def refresh_prices(security: Optional[str] = None, source: Optional[str] = None) -> Any:
    """Fehlende Kurse per Feed nachladen (temporär, nicht persistent).

    Args:
        security: Optional ein einzelnes Wertpapier (Name, ISIN, WKN, Ticker oder
            UUID); ohne Angabe werden alle aktiven Wertpapiere aktualisiert.
    """
    try:
        return registry.get(source).refresh_prices(security)
    except Exception as e:
        return _error(e)


@app.tool(
    description="Depotbewertung: Bestände (Stückzahl x Kurs) zu einem Stichtag. Berechnet "
                "die gehaltenen Stückzahlen je Wertpapier aus den Transaktionen und bewertet "
                "sie mit dem Kurs zum Stichtag. Ohne portfolio_name werden ALLE Depots "
                "zusammengefasst (Übertragungen zwischen Depots heben sich auf); ohne date "
                "wird der aktuellste Kurs verwendet. Depot als Name oder UUID; date ISO "
                "YYYY-MM-DD. Kurse/Werte in der Währung des Wertpapiers – KEINE "
                "Währungsumrechnung, Summen je Währung (totalsByCurrency). Positionen sind "
                "nach Wert absteigend sortiert." + _SOURCE_DOC
)
def get_holdings(
    portfolio_name: Optional[str] = None,
    date: Optional[str] = None,
    include_empty: bool = False,
    source: Optional[str] = None,
) -> Any:
    """Bestände und Bewertung zu einem Stichtag.

    Args:
        portfolio_name: Depot als Name oder UUID. Leer = alle Depots zusammengefasst.
        date: Stichtag, ISO-Format YYYY-MM-DD. Leer = aktuellster Kurs.
        include_empty: Auch vollständig verkaufte Positionen (Bestand 0) auflisten.
    """
    try:
        return registry.get(source).holdings(
            portfolio=portfolio_name, date=date, include_empty=include_empty
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Wertverlauf des Depots über die Zeit (für Charts): wiederholt die "
                "Depotbewertung für eine Serie von Stichtagen zwischen date_from und "
                "date_to (inklusive), im gewünschten Intervall ('daily', 'weekly' oder "
                "'monthly', Standard 'monthly'). Liefert je Stichtag nur die Summen je "
                "Währung (totalsByCurrency), keine Einzelpositionen – für "
                "Einzelpositionen zu einem bestimmten Datum get_holdings verwenden. "
                "Ohne date_from wird das Datum der ersten Transaktion verwendet, ohne "
                "date_to das heutige Datum. Ohne portfolio_name werden ALLE Depots "
                "zusammengefasst. KEINE Währungsumrechnung." + _SOURCE_DOC
)
def get_holdings_history(
    portfolio_name: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = "monthly",
    source: Optional[str] = None,
) -> Any:
    """Wertverlauf des Depots über mehrere Stichtage.

    Args:
        portfolio_name: Depot als Name oder UUID. Leer = alle Depots zusammengefasst.
        date_from: Startdatum inklusive, ISO-Format YYYY-MM-DD. Leer = erste Transaktion.
        date_to: Enddatum inklusive, ISO-Format YYYY-MM-DD. Leer = heute.
        interval: 'daily', 'weekly' oder 'monthly' (Standard).
    """
    try:
        return registry.get(source).holdings_history(
            portfolio=portfolio_name, date_from=date_from, date_to=date_to, interval=interval
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Unrealisierter Kurserfolg je Position (offene Bestände): aktueller Wert "
                "minus Einstandswert nach der gleitenden-Durchschnittspreis-Methode (wie "
                "der PP-Standard, keine FIFO-Methode). Liefert je Position "
                "avgCostPerShareWithFees/WithoutFees, costBasisWithFees/WithoutFees und "
                "unrealizedGainWithFees/WithoutFees – 'WithFees' bezieht Kauf-/Verkaufs-"
                "gebühren und -steuern mit ein, 'WithoutFees' rechnet sie heraus. Ohne "
                "portfolio_name werden ALLE Depots zusammengefasst; ohne date wird der "
                "aktuellste Kurs verwendet. Mit security wird auf ein einzelnes Wertpapier "
                "gefiltert (Name, ISIN, WKN, Ticker oder UUID, wie bei get_transactions/"
                "get_price_history). KEINE Währungsumrechnung, Summen je Währung."
                + _SOURCE_DOC
)
def get_unrealized_gains(
    portfolio_name: Optional[str] = None,
    date: Optional[str] = None,
    include_empty: bool = False,
    security: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Unrealisierter Kurserfolg je Position zu einem Stichtag.

    Args:
        portfolio_name: Depot als Name oder UUID. Leer = alle Depots zusammengefasst.
        date: Stichtag, ISO-Format YYYY-MM-DD. Leer = aktuellster Kurs.
        include_empty: Auch vollständig verkaufte Positionen (Bestand 0) auflisten.
        security: Wertpapier als Name, ISIN, WKN, Ticker oder UUID. Leer = alle Positionen.
    """
    try:
        return registry.get(source).unrealized_gains(
            portfolio=portfolio_name, date=date, include_empty=include_empty, security=security
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Realisierter Kurserfolg je Wertpapier aus Verkäufen (SALE/"
                "OUTBOUND_DELIVERY) im Zeitraum, nach der gleitenden-Durchschnittspreis-"
                "Methode (wie der PP-Standard, keine FIFO-Methode). Liefert je Position "
                "sharesSold, proceedsWithFees/WithoutFees, costBasisWithFees/WithoutFees "
                "und realizedGainWithFees/WithoutFees – 'WithFees' bezieht Verkaufsgebühren/"
                "-steuern und die Gebühren der ursprünglichen Käufe mit ein, 'WithoutFees' "
                "rechnet sie heraus. Ohne portfolio_name werden ALLE Depots zusammengefasst; "
                "ohne date_from/date_to der gesamte Datenbestand. Mit security wird auf ein "
                "einzelnes Wertpapier gefiltert (Name, ISIN, WKN, Ticker oder UUID, wie bei "
                "get_transactions/get_price_history). KEINE Währungsumrechnung, "
                "Summen je Währung." + _SOURCE_DOC
)
def get_realized_gains(
    portfolio_name: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    security: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Realisierter Kurserfolg je Wertpapier im Zeitraum.

    Args:
        portfolio_name: Depot als Name oder UUID. Leer = alle Depots zusammengefasst.
        date_from: Startdatum inklusive, ISO-Format YYYY-MM-DD.
        date_to: Enddatum inklusive, ISO-Format YYYY-MM-DD.
        security: Wertpapier als Name, ISIN, WKN, Ticker oder UUID. Leer = alle Positionen.
    """
    try:
        return registry.get(source).realized_gains(
            portfolio=portfolio_name, date_from=date_from, date_to=date_to, security=security
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Kontostand (Saldo) eines Verrechnungskontos zu einem Stichtag. "
                "Berechnet den Saldo direkt aus allen kontobewegenden Transaktionen "
                "(DEPOSIT/REMOVAL/DIVIDEND/INTEREST/INTEREST_CHARGE/TAX/TAX_REFUND/"
                "FEE/FEE_REFUND/PURCHASE/SALE sowie CASH_TRANSFER zwischen zwei "
                "Konten) – NICHT durch manuelles Aufsummieren von get_transactions "
                "nachbilden, das ist fehleranfällig (Vorzeichen, Konto-zu-Konto-"
                "Transfers). Konto als Name oder UUID; date ISO YYYY-MM-DD, ohne "
                "Angabe wird der gesamte Datenbestand (aktuellster Stand) verwendet. "
                "Saldo als String (exakter Dezimalwert) in der Kontowährung."
                + _SOURCE_DOC
)
def get_account_balance(
    account: str,
    date: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Kontostand (Saldo) eines Verrechnungskontos.

    Args:
        account: Konto als Name oder UUID.
        date: Stichtag, ISO-Format YYYY-MM-DD. Leer = aktueller Gesamtstand.
    """
    try:
        return registry.get(source).account_balance(account, date=date)
    except Exception as e:
        return _error(e)


# ==================== Taxonomien / Allokation ====================

@app.tool(
    description="Alle Taxonomien (Klassifikationsbäume aus Portfolio Performance, z.B. "
                "Anlagekategorien, Regionen, Branchen, Asset Allocation) mit ihrer "
                "hierarchischen Klassifikationsstruktur (id/parentId/name/color) und den "
                "je Klassifikation zugewiesenen Wertpapieren/Konten (vehicleUuid/"
                "vehicleName/weight). 'weight' ist auf einer Skala 0..10000 (10000 = 100%). "
                "Dient als Nachschlagewerk für den taxonomy-Parameter von get_asset_allocation."
                + _SOURCE_DOC
)
def list_taxonomies(source: Optional[str] = None) -> Any:
    """Liste aller Taxonomien mit Klassifikationsbaum und Zuweisungen."""
    try:
        return registry.get(source).list_taxonomies()
    except Exception as e:
        return _error(e)


@app.tool(
    description="Portfolio-Allokation nach einer Taxonomie (z.B. Anlagekategorien, "
                "Regionen, Branchen): verteilt den aktuellen Bestandswert der Wertpapiere "
                "(und, ohne portfolio_name-Filter, Kontostände zugewiesener Verrechnungs-"
                "konten, z.B. für 'Barvermögen') gemäß der in Portfolio Performance "
                "hinterlegten Klassifikations-Zuweisung auf einen Stichtag. Ohne taxonomy "
                "wird die einzige vorhandene Taxonomie verwendet (bei mehreren siehe "
                "list_taxonomies für gültige Namen/UUIDs). Wertpapiere/Konten ohne "
                "Zuweisung in dieser Taxonomie landen unter 'Nicht klassifiziert'. "
                "KEINE Währungsumrechnung, Summen je Währung." + _SOURCE_DOC
)
def get_asset_allocation(
    taxonomy: Optional[str] = None,
    date: Optional[str] = None,
    portfolio_name: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Bestandswert verteilt auf die Klassifikationen einer Taxonomie.

    Args:
        taxonomy: Taxonomie als Name oder UUID (siehe list_taxonomies). Leer = einzige
            vorhandene Taxonomie, falls nur eine konfiguriert ist.
        date: Stichtag, ISO-Format YYYY-MM-DD. Leer = aktuellster Kurs.
        portfolio_name: Depot als Name oder UUID. Leer = alle Depots zusammengefasst
            (dann werden auch zugewiesene Kontostände berücksichtigt).
    """
    try:
        return registry.get(source).asset_allocation(
            taxonomy=taxonomy, date=date, portfolio=portfolio_name
        )
    except Exception as e:
        return _error(e)


# ==================== Sparpläne ====================

@app.tool(
    description="Liste der Sparpläne/Investmentpläne (automatische Wertpapierkäufe/"
                "-verkäufe oder Konto-Ein-/Auszahlungen) mit Wertpapier/Depot/Konto, "
                "Betrag, Startdatum, intervalMonths (Abstand zwischen Ausführungen in "
                "Monaten) und der Anzahl bereits generierter Transaktionen."
                + _SOURCE_DOC
)
def list_investment_plans(source: Optional[str] = None) -> Any:
    """Liste aller Sparpläne/Investmentpläne."""
    try:
        return registry.get(source).investment_plans()
    except Exception as e:
        return _error(e)


# ==================== Transaktionen / Reports ====================

@app.tool(
    description="Gefilterte Transaktionen abrufen. Alle Filter sind optional und werden "
                "kombiniert (UND-Verknüpfung). Konto/Depot/Wertpapier können als Name oder "
                "UUID angegeben werden. Deckt z.B. 'alle Umsätze eines Kontos im Zeitraum' "
                "(account setzen) und 'alle Depottransaktionen bestimmter Arten' "
                "(portfolio + types setzen) ab. Ergebnis ist nach Datum sortiert und mit "
                "accountName/portfolioName/securityName angereichert." + _SOURCE_DOC
)
def get_transactions(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    types: Optional[List[str]] = None,
    account: Optional[str] = None,
    portfolio_name: Optional[str] = None,
    security: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Gefilterte Transaktionen.

    Args:
        date_from: Startdatum inklusive, ISO-Format YYYY-MM-DD.
        date_to: Enddatum inklusive, ISO-Format YYYY-MM-DD.
        types: Liste von Transaktionsarten (siehe list_transaction_types).
        account: Konto als Name oder UUID.
        portfolio_name: Depot als Name oder UUID.
        security: Wertpapier als Name oder UUID.
    """
    try:
        return registry.get(source).filter_transactions(
            date_from=date_from,
            date_to=date_to,
            types=types,
            account=account,
            portfolio=portfolio_name,
            security=security,
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Aggregierte Zusammenfassung für Reports: Summen und Anzahl je "
                "Transaktionsart sowie Gesamtsumme im Zeitraum. Optional auf ein Konto "
                "oder Depot einschränken (Name oder UUID)." + _SOURCE_DOC
)
def get_transaction_summary(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    account: Optional[str] = None,
    portfolio_name: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Summen je Typ + Gesamtsumme im Zeitraum."""
    try:
        return registry.get(source).summarize(
            date_from=date_from,
            date_to=date_to,
            account=account,
            portfolio=portfolio_name,
        )
    except Exception as e:
        return _error(e)


# ==================== Utility ====================

@app.tool(description="Ping – prüft, ob der MCP-Server läuft.")
def ping() -> str:
    return "pong"


# ==================== Authentifizierung (optional) ====================

class BearerAuthMiddleware:
    """Reine ASGI-Middleware, die 'Authorization: Bearer <token>' erzwingt.

    Bewusst als rohe ASGI-Middleware (nicht BaseHTTPMiddleware) umgesetzt, damit
    langlebige SSE-/streamable-http-Streams nicht gepuffert werden.
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        provided = b""
        for name, value in scope.get("headers") or []:
            if name == b"authorization":
                provided = value
                break

        if not hmac.compare_digest(provided, self._expected):
            body = b'{"error": "unauthorized"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)


def build_mcp_asgi_app(transport: str):
    """Baut die MCP-Starlette-App für den Transport, inkl. optionaler Bearer-Auth."""
    if transport == "streamable-http":
        starlette_app = app.streamable_http_app()
    else:
        starlette_app = app.sse_app()

    token = (settings.MCP_AUTH_TOKEN or "").strip()
    if token:
        starlette_app.add_middleware(BearerAuthMiddleware, token=token)
        logger.info("MCP Bearer-Token-Authentifizierung ist AKTIV")
    else:
        logger.warning(
            "MCP_AUTH_TOKEN ist nicht gesetzt – der Server läuft OHNE Authentifizierung. "
            "Vor Remote-Zugriff bitte MCP_AUTH_TOKEN setzen."
        )
    return starlette_app
