"""MCP server for Portfolio Performance.

Provides read-only tools to query filtered account and portfolio data from a
Portfolio Performance file and build reports from it.

Terminology (see also instructions below): 'source' (parameter 'source') =
one complete .portfolio file; 'portfolio' (parameter 'portfolio_name') =
a securities portfolio/depot within a source; 'account' (parameter 'account')
= a cash account within a source.

All tools are thin wrappers around `src.portfolio`. Errors are not raised,
they are returned as `{"status": "error", "message": ...}` (same convention
as mail-mcp).
"""
import hmac
import logging
from typing import List, Dict, Optional, Any

from mcp.server import FastMCP

from src.config import settings
from src.portfolio import registry, TRANSACTION_TYPES

_SOURCE_DOC = (
    " Optional: 'source' selects the source (id from list_data_sources, one "
    "complete .portfolio file – NOT a portfolio/depot) when multiple files are "
    "configured; can be omitted if only one source is configured."
)

logger = logging.getLogger(__name__)

app = FastMCP(
    name="pp-mcp-server",
    host=settings.MCP_SERVER_HOST,
    port=settings.MCP_SERVER_PORT,
    instructions=(
        "MCP server for Portfolio Performance. Provides filtered account and "
        "portfolio data (transactions by type/date range) for reports. "
        "Terminology: 'source' (parameter 'source') = one complete .portfolio "
        "file, see list_data_sources. 'portfolio' (parameter 'portfolio_name') "
        "= a securities portfolio/depot within a source, see list_portfolios. "
        "'account' (parameter 'account') = a cash account within a source, see "
        "list_accounts. 'security' (parameter 'security') = a stock/fund/ETF "
        "etc., see list_securities. The word 'portfolio' alone can be "
        "ambiguous with 'source' (a source is also a Portfolio Performance "
        "file) – when unclear, check list_data_sources and list_portfolios "
        "first to clarify which one is meant. "
        f"Version {settings.APP_VERSION}"
    ),
)


def _error(e: Exception) -> Dict[str, Any]:
    """Converts an exception into a client response.

    For FileNotFoundError, the full server file path is NOT passed to the
    client (would leak information about the server environment) – only
    logged.
    """
    logger.error(f"Error: {e}")
    if isinstance(e, FileNotFoundError):
        return {
            "status": "error",
            "message": "Portfolio file not found or not readable (see server log).",
        }
    return {"status": "error", "message": str(e)}


# ==================== File / master data ====================

@app.tool(
    description="Configured sources (id + label), each a complete .portfolio "
                "file, for the 'source' parameter of the other tools (NOT the "
                "portfolios/depots within a file, see list_portfolios for those). "
                "When exactly one source is configured, 'source' is optional "
                "everywhere."
)
def list_data_sources() -> Any:
    """Configured sources (without paths/passwords)."""
    return registry.list_sources()


@app.tool(
    description="Information about the portfolio file: path, modification date, "
                "encrypted yes/no, version, base currency, number of accounts/"
                "portfolios/securities/transactions, and earliest/latest "
                "transaction date." + _SOURCE_DOC
)
def get_file_info(source: Optional[str] = None) -> Dict[str, Any]:
    """Metadata and key figures about the portfolio file."""
    try:
        return registry.get(source).file_info()
    except Exception as e:
        return _error(e)


@app.tool(
    description="All accounts (cash accounts) with uuid, name, currencyCode "
                "and isRetired." + _SOURCE_DOC
)
def list_accounts(source: Optional[str] = None) -> Any:
    """List of all accounts."""
    try:
        return registry.get(source).list_accounts()
    except Exception as e:
        return _error(e)


@app.tool(
    description="All portfolios/depots of a source (Portfolio Performance's "
                "internal term is 'portfolio') with uuid, name, reference "
                "account and isRetired. NOT to be confused with the 'source' "
                "parameter (a source is a whole .portfolio file, see "
                "list_data_sources)." + _SOURCE_DOC
)
def list_portfolios(source: Optional[str] = None) -> Any:
    """List of all portfolios/depots."""
    try:
        return registry.get(source).list_portfolios()
    except Exception as e:
        return _error(e)


@app.tool(
    description="All securities with uuid, name, isin, wkn, tickerSymbol, "
                "currencyCode and isRetired (marked inactive in PP)."
                + _SOURCE_DOC
)
def list_securities(source: Optional[str] = None) -> Any:
    """List of all securities."""
    try:
        return registry.get(source).list_securities()
    except Exception as e:
        return _error(e)


@app.tool(
    description="List of valid transaction types as a filter aid "
                "(e.g. DIVIDEND, INTEREST, TAX, PURCHASE, SALE, DEPOSIT, "
                "REMOVAL, FEE)."
)
def list_transaction_types() -> List[str]:
    """Available transaction types (source-independent)."""
    return TRANSACTION_TYPES


# ==================== Prices ====================

@app.tool(
    description="Most recent known price of a security. Uses the last "
                "fetched price (latest) if available, otherwise the most "
                "recent historical closing price. Security as name, ISIN, "
                "WKN, ticker or UUID. Price as a string (exact decimal), date "
                "in ISO YYYY-MM-DD, 'source' field in the result = "
                "latest|historical." + _SOURCE_DOC
)
def get_latest_price(security: str, source: Optional[str] = None) -> Any:
    """Most recent price of a security.

    Args:
        security: Security as name, ISIN, WKN, ticker or UUID.
    """
    try:
        return registry.get(source).latest_price(security)
    except Exception as e:
        return _error(e)


@app.tool(
    description="Historical daily closing prices of a security in a date "
                "range (bounds inclusive), sorted by date. Security as name, "
                "ISIN, WKN, ticker or UUID. Without a date range ALL prices "
                "are returned (can be several thousand) – use limit to get "
                "only the last N. Prices as strings." + _SOURCE_DOC
)
def get_price_history(
    security: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: Optional[int] = None,
    source: Optional[str] = None,
) -> Any:
    """Historical closing prices in a date range.

    Args:
        security: Security as name, ISIN, WKN, ticker or UUID.
        date_from: Start date inclusive, ISO format YYYY-MM-DD.
        date_to: End date inclusive, ISO format YYYY-MM-DD.
        limit: Return only the last N prices of the range.
    """
    try:
        return registry.get(source).price_history(
            security, date_from=date_from, date_to=date_to, limit=limit
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Price of a security as of a given date. If there is no "
                "price on that exact day, the last price before it is "
                "returned (exact=false). Useful for point-in-time valuations "
                "(e.g. year end). Security as name, ISIN, WKN, ticker or "
                "UUID; date in ISO YYYY-MM-DD." + _SOURCE_DOC
)
def get_price_on(security: str, date: str, source: Optional[str] = None) -> Any:
    """Price as of a given date (exact or last one before it).

    Args:
        security: Security as name, ISIN, WKN, ticker or UUID.
        date: Reference date, ISO format YYYY-MM-DD.
    """
    try:
        return registry.get(source).price_on(security, date)
    except Exception as e:
        return _error(e)


@app.tool(
    description="Most recent price of ALL securities as an overview (uuid, "
                "name, isin, wkn, tickerSymbol, currencyCode, date, close, "
                "source). For portfolio reports across all positions. Prices "
                "as strings." + _SOURCE_DOC
)
def list_latest_prices(source: Optional[str] = None) -> Any:
    """Most recent price of all securities."""
    try:
        return registry.get(source).list_latest_prices()
    except Exception as e:
        return _error(e)


@app.tool(
    description="Price update configuration (feed type + feed URL, "
                "historical and 'latest') of all ACTIVE securities "
                "(isRetired=false). Useful to see which external feed (e.g. "
                "ariva.de) a security gets its prices from, before calling "
                "refresh_prices." + _SOURCE_DOC
)
def list_price_feeds(source: Optional[str] = None) -> Any:
    """Price update configuration of all active securities."""
    try:
        return registry.get(source).list_price_feeds()
    except Exception as e:
        return _error(e)


@app.tool(
    description="Fetches missing, more recent prices via the price feed "
                "configured in the portfolio file and holds them ONLY "
                "TEMPORARILY in memory (no write access to the .portfolio "
                "file) – afterwards get_latest_price/get_price_history/"
                "get_holdings/get_unrealized_gains automatically include "
                "these prices. Currently only feed type GENERIC_HTML_TABLE "
                "with an ariva.de host is supported; other feeds (e.g. PP, "
                "YAHOO) are skipped, not treated as an error. Without "
                "'security', all active securities are refreshed. The "
                "overlay is discarded as soon as the file is reloaded "
                "(change detected) or the server restarts." + _SOURCE_DOC
)
def refresh_prices(security: Optional[str] = None, source: Optional[str] = None) -> Any:
    """Fetch missing prices via feed (temporary, not persisted).

    Args:
        security: Optionally a single security (name, ISIN, WKN, ticker or
            UUID); without it, all active securities are refreshed.
    """
    try:
        return registry.get(source).refresh_prices(security)
    except Exception as e:
        return _error(e)


@app.tool(
    description="Portfolio valuation: holdings (share count x price) as of a "
                "given date. Computes the shares held per security from the "
                "transactions and values them at the price as of that date. "
                "Without portfolio_name, ALL portfolios are aggregated "
                "(transfers between portfolios cancel out); without date, the "
                "most recent price is used. Portfolio as name or UUID; date "
                "in ISO YYYY-MM-DD. Prices/values are in the security's "
                "currency – NO currency conversion, totals per currency "
                "(totalsByCurrency). Positions are sorted by value descending."
                + _SOURCE_DOC
)
def get_holdings(
    portfolio_name: Optional[str] = None,
    date: Optional[str] = None,
    include_empty: bool = False,
    source: Optional[str] = None,
) -> Any:
    """Holdings and valuation as of a given date.

    Args:
        portfolio_name: Portfolio/depot as name or UUID. Empty = all
            portfolios aggregated.
        date: Reference date, ISO format YYYY-MM-DD. Empty = most recent price.
        include_empty: Also list fully sold positions (zero balance).
    """
    try:
        return registry.get(source).holdings(
            portfolio=portfolio_name, date=date, include_empty=include_empty
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Value history of the portfolio over time (for charts): "
                "repeats the portfolio valuation for a series of dates "
                "between date_from and date_to (inclusive), at the desired "
                "interval ('daily', 'weekly' or 'monthly', default "
                "'monthly'). Returns only the totals per currency "
                "(totalsByCurrency) for each date, no individual positions – "
                "use get_holdings for individual positions on a specific "
                "date. Without date_from, the date of the first transaction "
                "is used; without date_to, today's date. Without "
                "portfolio_name, ALL portfolios are aggregated. NO currency "
                "conversion." + _SOURCE_DOC
)
def get_holdings_history(
    portfolio_name: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    interval: str = "monthly",
    source: Optional[str] = None,
) -> Any:
    """Value history of the portfolio across multiple dates.

    Args:
        portfolio_name: Portfolio/depot as name or UUID. Empty = all
            portfolios aggregated.
        date_from: Start date inclusive, ISO format YYYY-MM-DD. Empty = first
            transaction.
        date_to: End date inclusive, ISO format YYYY-MM-DD. Empty = today.
        interval: 'daily', 'weekly' or 'monthly' (default).
    """
    try:
        return registry.get(source).holdings_history(
            portfolio=portfolio_name, date_from=date_from, date_to=date_to, interval=interval
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Unrealized gain per position (open holdings): current value "
                "minus cost basis using the moving-average-cost method (as "
                "in PP's default, not FIFO). Returns per position "
                "avgCostPerShareWithFees/WithoutFees, costBasisWithFees/"
                "WithoutFees and unrealizedGainWithFees/WithoutFees – "
                "'WithFees' includes buy/sell fees and taxes, 'WithoutFees' "
                "excludes them. Without portfolio_name, ALL portfolios are "
                "aggregated; without date, the most recent price is used. "
                "With security, filters to a single security (name, ISIN, "
                "WKN, ticker or UUID, same as get_transactions/"
                "get_price_history). NO currency conversion, totals per "
                "currency." + _SOURCE_DOC
)
def get_unrealized_gains(
    portfolio_name: Optional[str] = None,
    date: Optional[str] = None,
    include_empty: bool = False,
    security: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Unrealized gain per position as of a given date.

    Args:
        portfolio_name: Portfolio/depot as name or UUID. Empty = all
            portfolios aggregated.
        date: Reference date, ISO format YYYY-MM-DD. Empty = most recent price.
        include_empty: Also list fully sold positions (zero balance).
        security: Security as name, ISIN, WKN, ticker or UUID. Empty = all
            positions.
    """
    try:
        return registry.get(source).unrealized_gains(
            portfolio=portfolio_name, date=date, include_empty=include_empty, security=security
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Realized gain per security from sales (SALE/"
                "OUTBOUND_DELIVERY) in a date range, using the "
                "moving-average-cost method (as in PP's default, not FIFO). "
                "Returns per position sharesSold, proceedsWithFees/"
                "WithoutFees, costBasisWithFees/WithoutFees and "
                "realizedGainWithFees/WithoutFees – 'WithFees' includes sell "
                "fees/taxes and the fees of the original purchases, "
                "'WithoutFees' excludes them. Without portfolio_name, ALL "
                "portfolios are aggregated; without date_from/date_to, the "
                "entire data set. With security, filters to a single "
                "security (name, ISIN, WKN, ticker or UUID, same as "
                "get_transactions/get_price_history). NO currency "
                "conversion, totals per currency." + _SOURCE_DOC
)
def get_realized_gains(
    portfolio_name: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    security: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Realized gain per security in a date range.

    Args:
        portfolio_name: Portfolio/depot as name or UUID. Empty = all
            portfolios aggregated.
        date_from: Start date inclusive, ISO format YYYY-MM-DD.
        date_to: End date inclusive, ISO format YYYY-MM-DD.
        security: Security as name, ISIN, WKN, ticker or UUID. Empty = all
            positions.
    """
    try:
        return registry.get(source).realized_gains(
            portfolio=portfolio_name, date_from=date_from, date_to=date_to, security=security
        )
    except Exception as e:
        return _error(e)


@app.tool(
    description="Balance of a cash account as of a given date. Computes the "
                "balance directly from all balance-affecting transactions "
                "(DEPOSIT/REMOVAL/DIVIDEND/INTEREST/INTEREST_CHARGE/TAX/"
                "TAX_REFUND/FEE/FEE_REFUND/PURCHASE/SALE, as well as "
                "CASH_TRANSFER between two accounts) – do NOT reconstruct "
                "this by manually summing get_transactions, that is "
                "error-prone (signs, account-to-account transfers). Account "
                "as name or UUID; date in ISO YYYY-MM-DD, without it the "
                "entire data set (most recent state) is used. Balance as a "
                "string (exact decimal) in the account's currency."
                + _SOURCE_DOC
)
def get_account_balance(
    account: str,
    date: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Balance of a cash account.

    Args:
        account: Account as name or UUID.
        date: Reference date, ISO format YYYY-MM-DD. Empty = current overall
            balance.
    """
    try:
        return registry.get(source).account_balance(account, date=date)
    except Exception as e:
        return _error(e)


# ==================== Taxonomies / allocation ====================

@app.tool(
    description="All taxonomies (classification trees from Portfolio "
                "Performance, e.g. asset classes, regions, industries, asset "
                "allocation) with their hierarchical classification structure "
                "(id/parentId/name/color) and the securities/accounts "
                "assigned to each classification (vehicleUuid/vehicleName/"
                "weight). 'weight' is on a scale of 0..10000 (10000 = 100%). "
                "Serves as a lookup for the taxonomy parameter of "
                "get_asset_allocation." + _SOURCE_DOC
)
def list_taxonomies(source: Optional[str] = None) -> Any:
    """List of all taxonomies with classification tree and assignments."""
    try:
        return registry.get(source).list_taxonomies()
    except Exception as e:
        return _error(e)


@app.tool(
    description="Portfolio allocation by a taxonomy (e.g. asset classes, "
                "regions, industries): distributes the current holdings "
                "value of the securities (and, without a portfolio_name "
                "filter, balances of assigned cash accounts, e.g. for 'cash') "
                "according to the classification assignment stored in "
                "Portfolio Performance, as of a given date. Without taxonomy, "
                "the only existing taxonomy is used (with several, see "
                "list_taxonomies for valid names/UUIDs). Securities/accounts "
                "without an assignment in this taxonomy end up under "
                "'Unclassified'. NO currency conversion, totals per currency."
                + _SOURCE_DOC
)
def get_asset_allocation(
    taxonomy: Optional[str] = None,
    date: Optional[str] = None,
    portfolio_name: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Holdings value distributed across the classifications of a taxonomy.

    Args:
        taxonomy: Taxonomy as name or UUID (see list_taxonomies). Empty = the
            only existing taxonomy, if only one is configured.
        date: Reference date, ISO format YYYY-MM-DD. Empty = most recent price.
        portfolio_name: Portfolio/depot as name or UUID. Empty = all
            portfolios aggregated (assigned account balances are then also
            included).
    """
    try:
        return registry.get(source).asset_allocation(
            taxonomy=taxonomy, date=date, portfolio=portfolio_name
        )
    except Exception as e:
        return _error(e)


# ==================== Investment plans ====================

@app.tool(
    description="List of investment/savings plans (automatic security buys/"
                "sells or account deposits/withdrawals) with security/"
                "portfolio/account, amount, start date, intervalMonths "
                "(spacing between executions in months) and the number of "
                "transactions already generated." + _SOURCE_DOC
)
def list_investment_plans(source: Optional[str] = None) -> Any:
    """List of all investment/savings plans."""
    try:
        return registry.get(source).investment_plans()
    except Exception as e:
        return _error(e)


# ==================== Transactions / reports ====================

@app.tool(
    description="Retrieve filtered transactions. All filters are optional and "
                "combined with AND. Account/portfolio/security can be given "
                "as name or UUID. Covers e.g. 'all transactions of an "
                "account in a date range' (set account) and 'all portfolio "
                "transactions of certain types' (set portfolio_name + "
                "types). Result is sorted by date and enriched with "
                "accountName/portfolioName/securityName." + _SOURCE_DOC
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
    """Filtered transactions.

    Args:
        date_from: Start date inclusive, ISO format YYYY-MM-DD.
        date_to: End date inclusive, ISO format YYYY-MM-DD.
        types: List of transaction types (see list_transaction_types).
        account: Account as name or UUID.
        portfolio_name: Portfolio/depot as name or UUID.
        security: Security as name or UUID.
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
    description="Aggregated summary for reports: sums and count per "
                "transaction type as well as the total for the date range. "
                "Optionally restrict to one account or portfolio (name or "
                "UUID)." + _SOURCE_DOC
)
def get_transaction_summary(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    account: Optional[str] = None,
    portfolio_name: Optional[str] = None,
    source: Optional[str] = None,
) -> Any:
    """Sums per type + total for the date range."""
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

@app.tool(description="Ping – checks whether the MCP server is running.")
def ping() -> str:
    return "pong"


# ==================== Authentication (optional) ====================

class BearerAuthMiddleware:
    """Raw ASGI middleware that enforces 'Authorization: Bearer <token>'.

    Deliberately implemented as raw ASGI middleware (not BaseHTTPMiddleware)
    so that long-lived SSE/streamable-http streams are not buffered.
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
    """Builds the MCP Starlette app for the transport, incl. optional bearer auth."""
    if transport == "streamable-http":
        starlette_app = app.streamable_http_app()
    else:
        starlette_app = app.sse_app()

    token = (settings.MCP_AUTH_TOKEN or "").strip()
    if token:
        starlette_app.add_middleware(BearerAuthMiddleware, token=token)
        logger.info("MCP bearer token authentication is ACTIVE")
    else:
        logger.warning(
            "MCP_AUTH_TOKEN is not set – the server is running WITHOUT "
            "authentication. Set MCP_AUTH_TOKEN before remote access."
        )
    return starlette_app
