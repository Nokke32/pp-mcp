"""Data access for the Portfolio Performance file.

Wraps the (vendored) parser and provides:
- an mtime-based cache so the file is only re-parsed when it changes,
- resolution of account/portfolio/security names to UUIDs (and vice versa),
- enrichment of transactions with readable names,
- filter and aggregation functions for reports,
- JSON-safe serialization (Decimal -> str, date -> ISO string).
"""
import json
import os
import datetime
from collections import defaultdict
from decimal import Decimal
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from src.config import settings
from src.pp_parser import parse_portfolio_file
from src.price_feed import fetch_ariva_prices, is_safe_url, ALLOWED_HOSTS


# All known transaction types (from client.proto, PTransaction.Type)
TRANSACTION_TYPES = [
    "PURCHASE",
    "SALE",
    "SECURITY_TRANSFER",
    "CASH_TRANSFER",
    "DEPOSIT",
    "REMOVAL",
    "DIVIDEND",
    "INTEREST",
    "INTEREST_CHARGE",
    "TAX",
    "TAX_REFUND",
    "FEE",
    "FEE_REFUND",
]


def _serialize(value: Any) -> Any:
    """Recursively converts Decimal/date values into JSON-safe types."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


class PortfolioNotConfigured(Exception):
    """Raised when no valid file path is configured."""


class Portfolio:
    """Cache wrapper around the portfolio file with mtime invalidation."""

    def __init__(self, file_path: str, password: Optional[str] = None):
        self.file_path = file_path
        self.password = password or None
        self._data: Optional[dict] = None
        self._mtime: Optional[float] = None
        # Lookup maps uuid -> name
        self._account_names: Dict[str, str] = {}
        self._portfolio_names: Dict[str, str] = {}
        self._security_names: Dict[str, str] = {}
        self._security_isins: Dict[str, Optional[str]] = {}
        # Temporary price overlay (uuid -> additional {date, close} entries),
        # populated by refresh_prices. Never written back to the file; it is
        # discarded on every real reload of the file (mtime change).
        self._price_overlay: Dict[str, List[Dict[str, Any]]] = {}

    # ---------------------------------------------------------------- loading
    def _ensure_loaded(self) -> dict:
        """(Re-)loads/parses the file if it has changed since last time."""
        if not self.file_path:
            raise PortfolioNotConfigured(
                "PP_FILE_PATH is not set. Please configure the path to the .portfolio file."
            )
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Portfolio file not found: {self.file_path}")

        mtime = os.path.getmtime(self.file_path)
        if self._data is None or mtime != self._mtime:
            self._data = parse_portfolio_file(self.file_path, self.password)
            self._mtime = mtime
            self._price_overlay = {}
            self._build_indexes()
        return self._data

    def _build_indexes(self) -> None:
        """Rebuilds the UUID->name lookups after parsing."""
        assert self._data is not None
        self._account_names = {a["uuid"]: a["name"] for a in self._data["accounts"]}
        self._portfolio_names = {p["uuid"]: p["name"] for p in self._data["portfolios"]}
        self._security_names = {s["uuid"]: s["name"] for s in self._data["securities"]}
        self._security_isins = {s["uuid"]: s.get("isin") for s in self._data["securities"]}

    # ------------------------------------------------------------- resolving
    @staticmethod
    def _resolve(identifier: Optional[str], entries: List[dict]) -> Optional[str]:
        """Resolves an identifier (UUID or name, case-insensitive) to a UUID.

        Returns None if no identifier was given. Raises ValueError if the
        identifier cannot be resolved unambiguously.
        """
        if not identifier:
            return None
        ident = identifier.strip()
        # Direct UUID match
        for e in entries:
            if e["uuid"] == ident:
                return e["uuid"]
        # Case-insensitive name comparison
        matches = [e for e in entries if e["name"].lower() == ident.lower()]
        if len(matches) == 1:
            return matches[0]["uuid"]
        if len(matches) > 1:
            raise ValueError(f"Identifier '{identifier}' is not unique.")
        raise ValueError(f"No entry found for '{identifier}'.")

    # ---------------------------------------------------------- public API
    def file_info(self) -> Dict[str, Any]:
        """Metadata and metrics about the configured file."""
        data = self._ensure_loaded()
        with open(self.file_path, "rb") as f:
            header = f.read(9)
        encrypted = header.startswith(b"PORTFOLIO")
        dates = [t["date"] for t in data["transactions"] if t.get("date")]
        return {
            "path": self.file_path,
            "modified": datetime.datetime.fromtimestamp(self._mtime).isoformat() if self._mtime else None,
            "size_bytes": os.path.getsize(self.file_path),
            "encrypted": encrypted,
            "version": data["version"],
            "baseCurrency": data["baseCurrency"],
            "counts": {
                "accounts": len(data["accounts"]),
                "portfolios": len(data["portfolios"]),
                "securities": len(data["securities"]),
                "transactions": len(data["transactions"]),
            },
            "earliestTransaction": min(dates).date().isoformat() if dates else None,
            "latestTransaction": max(dates).date().isoformat() if dates else None,
        }

    def list_accounts(self) -> List[Dict[str, Any]]:
        data = self._ensure_loaded()
        return [_serialize(a) for a in data["accounts"]]

    def list_portfolios(self) -> List[Dict[str, Any]]:
        data = self._ensure_loaded()
        result = []
        for p in data["portfolios"]:
            item = dict(p)
            item["referenceAccountName"] = self._account_names.get(p.get("referenceAccountUuid"))
            result.append(_serialize(item))
        return result

    def list_securities(self) -> List[Dict[str, Any]]:
        data = self._ensure_loaded()
        # Prices/events are too extensive for report overviews -> omit them
        keys = ("uuid", "name", "isin", "wkn", "tickerSymbol", "currencyCode", "isRetired")
        return [_serialize({k: s.get(k) for k in keys}) for s in data["securities"]]

    # ---------------------------------------------------------------- prices
    @staticmethod
    def _describe_securities(securities: List[dict], limit: int = 10) -> str:
        """Short description ('Name (ISIN)') of several securities for error messages."""
        parts = [
            f"{s.get('name')} ({s.get('isin')})" if s.get("isin") else str(s.get("name"))
            for s in securities[:limit]
        ]
        if len(securities) > limit:
            parts.append(f"… ({len(securities) - limit} more)")
        return ", ".join(parts)

    def _find_security(self, identifier: Optional[str]) -> dict:
        """Resolves a security by name, ISIN, WKN, ticker, or UUID (case-insensitive).

        First tries an exact match; if that yields nothing, falls back to a
        substring search (e.g. "Adidas" finds "Adidas AG"). Returns the raw
        security dict (including prices/latest). Raises ValueError with a
        candidate list if nothing or no unambiguous match is found.
        """
        data = self._ensure_loaded()
        if not identifier or not identifier.strip():
            raise ValueError("No security specified.")
        ident = identifier.strip()
        for s in data["securities"]:
            if s["uuid"] == ident:
                return s
        low = ident.lower()
        matches = [
            s for s in data["securities"]
            if (s.get("name") or "").lower() == low
            or (s.get("isin") or "").lower() == low
            or (s.get("wkn") or "").lower() == low
            or (s.get("tickerSymbol") or "").lower() == low
        ]
        if not matches:
            matches = [
                s for s in data["securities"]
                if low in (s.get("name") or "").lower()
                or low in (s.get("isin") or "").lower()
                or low in (s.get("wkn") or "").lower()
                or low in (s.get("tickerSymbol") or "").lower()
            ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                f"Security '{identifier}' is not unique. "
                f"Matches: {self._describe_securities(matches)}"
            )
        raise ValueError(f"No security found for '{identifier}'.")

    @staticmethod
    def _security_meta(s: dict) -> Dict[str, Any]:
        """Identifying master data of a security (without price series)."""
        return {k: s.get(k) for k in ("uuid", "name", "isin", "wkn", "tickerSymbol", "currencyCode")}

    def _effective_prices(self, s: dict) -> List[Dict[str, Any]]:
        """Actual prices from the file plus the temporary price overlay (`refresh_prices`).

        The overlay only adds dates missing from the file – actual file
        entries are never overwritten.
        """
        prices = s.get("prices", [])
        overlay = self._price_overlay.get(s["uuid"])
        if not overlay:
            return prices
        existing_dates = {p["date"] for p in prices}
        extra = [p for p in overlay if p["date"] not in existing_dates]
        return prices + extra if extra else prices

    def _newest_price(self, s: dict) -> Optional[Dict[str, Any]]:
        """Most recent price of a security: the newer of the latest field and
        the most recent historical/overlay price. Returns None if no price
        data is available."""
        candidates = []
        latest = s.get("latest")
        if latest and latest.get("close") is not None:
            candidates.append({"date": latest["date"], "close": latest["close"], "source": "latest"})
        prices = self._effective_prices(s)
        if prices:
            last = max(prices, key=lambda p: p["date"])
            candidates.append({"date": last["date"], "close": last["close"], "source": "historical"})
        if not candidates:
            return None
        return max(candidates, key=lambda p: p["date"])

    def latest_price(self, security: str) -> Dict[str, Any]:
        """Most recently known price of a security."""
        s = self._find_security(security)
        meta = self._security_meta(s)
        price = self._newest_price(s)
        if price is None:
            return _serialize({**meta, "price": None, "message": "No price data available."})
        return _serialize({**meta, **price})

    def price_history(
        self,
        security: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Historical daily closing prices within the period (inclusive of both bounds), sorted by date.

        Without a period, all prices are returned – this can be several
        thousand entries. With `limit`, only the last N prices of the period
        are returned.
        """
        s = self._find_security(security)
        df = datetime.date.fromisoformat(date_from) if date_from else None
        dt = datetime.date.fromisoformat(date_to) if date_to else None
        rows = [
            {"date": p["date"], "close": p["close"]}
            for p in self._effective_prices(s)
            if not (df and p["date"] < df) and not (dt and p["date"] > dt)
        ]
        rows.sort(key=lambda r: r["date"])
        if limit is not None and limit > 0:
            rows = rows[-limit:]
        return _serialize({
            **self._security_meta(s),
            "date_from": date_from,
            "date_to": date_to,
            "count": len(rows),
            "prices": rows,
        })

    def price_on(self, security: str, date: str) -> Dict[str, Any]:
        """Price on a given date: exact match, or – if there's no price on that day – the last one before it."""
        s = self._find_security(security)
        target = datetime.date.fromisoformat(date)
        candidates = [p for p in self._effective_prices(s) if p["date"] <= target]
        meta = self._security_meta(s)
        if not candidates:
            return _serialize({
                **meta, "requestedDate": date, "date": None, "close": None,
                "message": "No price available on or before the requested date.",
            })
        best = max(candidates, key=lambda p: p["date"])
        return _serialize({
            **meta,
            "requestedDate": date,
            "date": best["date"],
            "close": best["close"],
            "exact": best["date"] == target,
        })

    def list_latest_prices(self) -> List[Dict[str, Any]]:
        """Most recent price of all securities – overview for portfolio reports."""
        data = self._ensure_loaded()
        result = []
        for s in data["securities"]:
            price = self._newest_price(s)
            result.append({
                **self._security_meta(s),
                "date": price["date"] if price else None,
                "close": price["close"] if price else None,
                "source": price["source"] if price else None,
            })
        return _serialize(result)

    def list_price_feeds(self) -> List[Dict[str, Any]]:
        """Price update configuration (feed type + URL) of all active securities."""
        data = self._ensure_loaded()
        result = [
            {
                "uuid": s["uuid"],
                "name": s["name"],
                "isin": s.get("isin"),
                "feed": s.get("feed"),
                "feedURL": s.get("feedURL"),
                "latestFeed": s.get("latestFeed"),
                "latestFeedURL": s.get("latestFeedURL"),
            }
            for s in data["securities"]
            if not s.get("isRetired")
        ]
        return _serialize(result)

    def refresh_prices(self, security: Optional[str] = None) -> Dict[str, Any]:
        """Fetches missing, newer prices via the configured feed and stores
        them in the temporary price overlay (see `_effective_prices`). Does
        not modify the .portfolio file. Currently only the feed type
        GENERIC_HTML_TABLE with an ariva.de host is supported; other feeds
        (PP, YAHOO, ...) are skipped and not treated as errors.
        """
        data = self._ensure_loaded()
        if security:
            targets = [self._find_security(security)]
        else:
            targets = [s for s in data["securities"] if not s.get("isRetired")]

        refreshed: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for s in targets:
            name = s["name"]
            uuid = s["uuid"]
            feed = s.get("feed")
            feed_url = s.get("feedURL")
            if feed != "GENERIC_HTML_TABLE" or not feed_url:
                skipped.append({"uuid": uuid, "name": name, "reason": f"Feed type '{feed}' is not supported."})
                continue
            hostname = urlparse(feed_url).hostname
            if not hostname or hostname.lower() not in ALLOWED_HOSTS:
                skipped.append({"uuid": uuid, "name": name, "reason": "Feed URL is not a supported ariva.de address."})
                continue
            try:
                fetched = fetch_ariva_prices(feed_url)
            except Exception as e:
                errors.append({"uuid": uuid, "name": name, "message": str(e)})
                continue
            existing_dates = {p["date"] for p in s.get("prices", [])}
            new_entries = [p for p in fetched if p["date"] not in existing_dates]
            self._price_overlay[uuid] = new_entries
            refreshed.append({"uuid": uuid, "name": name, "addedCount": len(new_entries)})

        return _serialize({"refreshed": refreshed, "skipped": skipped, "errors": errors})

    # ------------------------------------------------------- holdings / valuation
    # Transaction types that change the share count in a portfolio (with sign).
    # SECURITY_TRANSFER is handled separately (source -, target +).
    _SHARE_SIGN = {
        "PURCHASE": Decimal(1),
        "INBOUND_DELIVERY": Decimal(1),
        "SALE": Decimal(-1),
        "OUTBOUND_DELIVERY": Decimal(-1),
    }

    def _price_asof(self, s: dict, target: Optional[datetime.date]):
        """Price of a security as of a given date (or the most recent one, if target is None).

        Returns (close, date, source). source: on_date | historical | latest | None.
        """
        if target is None:
            p = self._newest_price(s)
            return (p["close"], p["date"], p["source"]) if p else (None, None, None)
        candidates = [p for p in self._effective_prices(s) if p["date"] <= target]
        latest = s.get("latest")
        if latest and latest.get("close") is not None and latest["date"] <= target:
            candidates.append({"date": latest["date"], "close": latest["close"]})
        if not candidates:
            return (None, None, None)
        best = max(candidates, key=lambda p: p["date"])
        return (best["close"], best["date"], "on_date" if best["date"] == target else "historical")

    def _share_balances(
        self, portfolio_uuid: Optional[str], as_of: Optional[datetime.date]
    ) -> Dict[str, Decimal]:
        """Share count per security UUID up to and including `as_of` (or overall).

        Without `portfolio_uuid`, all portfolios are aggregated; transfers
        between portfolios then cancel out. With `portfolio_uuid`, only
        movements of that portfolio count (transfer source -, transfer target +).
        """
        data = self._ensure_loaded()
        bal: Dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        for t in data["transactions"]:
            sec = t.get("securityUuid")
            if not sec:
                continue
            d = t["date"].date() if t.get("date") else None
            if as_of and (d is None or d > as_of):
                continue
            shares = t.get("shares") or Decimal(0)
            if not shares:
                continue
            typ = t["type"]
            if typ in self._SHARE_SIGN:
                if portfolio_uuid and t.get("portfolioUuid") != portfolio_uuid:
                    continue
                bal[sec] += self._SHARE_SIGN[typ] * shares
            elif typ == "SECURITY_TRANSFER":
                src = t.get("portfolioUuid")
                tgt = t.get("otherPortfolioUuid")
                if portfolio_uuid is None:
                    continue  # cross-portfolio -> total holdings unchanged
                if src == portfolio_uuid:
                    bal[sec] -= shares
                elif tgt == portfolio_uuid:
                    bal[sec] += shares
        return bal

    def holdings(
        self,
        portfolio: Optional[str] = None,
        date: Optional[str] = None,
        include_empty: bool = False,
    ) -> Dict[str, Any]:
        """Holdings and valuation (share count x price) as of a given date.

        Without `portfolio`, all portfolios are aggregated; without `date`,
        the most recently known price is used. Prices are in the currency of
        the respective security; NO currency conversion takes place (totals
        per currency).
        """
        data = self._ensure_loaded()
        pf_uuid = self._resolve(portfolio, data["portfolios"]) if portfolio else None
        as_of = datetime.date.fromisoformat(date) if date else None

        bal = self._share_balances(pf_uuid, as_of)
        sec_by_uuid = {s["uuid"]: s for s in data["securities"]}

        positions: List[Dict[str, Any]] = []
        totals: Dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        missing_price = 0
        for sec_uuid, shares in bal.items():
            if shares == 0 and not include_empty:
                continue
            s = sec_by_uuid.get(sec_uuid)
            if s is None:
                continue
            close, price_date, source = self._price_asof(s, as_of)
            value = shares * close if close is not None else None
            currency = s.get("currencyCode")
            if value is not None:
                totals[currency] += value
            else:
                missing_price += 1
            positions.append({
                "uuid": sec_uuid,
                "name": s.get("name"),
                "isin": s.get("isin"),
                "currencyCode": currency,
                "shares": shares,
                "price": close,
                "priceDate": price_date,
                "priceSource": source,
                "value": value,
            })

        # largest position first; positions without a price go last
        positions.sort(key=lambda p: (p["value"] is None, -(p["value"] or Decimal(0))))

        notes = []
        if len(totals) > 1:
            notes.append("Multiple currencies – totals kept separate per currency, no conversion.")
        if missing_price:
            notes.append(f"No price available on the requested date for {missing_price} position(s) (value=null).")

        return _serialize({
            "portfolio": portfolio,
            "valuationDate": date,
            "baseCurrency": data["baseCurrency"],
            "positionCount": len(positions),
            "totalsByCurrency": {c: str(v) for c, v in sorted(totals.items())},
            "positions": positions,
            "note": " ".join(notes) if notes else None,
        })

    @staticmethod
    def _sample_dates(start: datetime.date, end: datetime.date, interval: str) -> List[datetime.date]:
        """Ascending sample dates between start and end (inclusive) at the requested interval.

        "monthly" returns month-end dates (the last date is always `end`
        itself, even if that's not a month end) – suitable for value-history
        charts.
        """
        if start > end:
            return []
        if interval == "daily":
            dates = []
            d = start
            while d <= end:
                dates.append(d)
                d += datetime.timedelta(days=1)
            return dates
        if interval == "weekly":
            dates = []
            d = start
            while d <= end:
                dates.append(d)
                d += datetime.timedelta(days=7)
            if dates[-1] != end:
                dates.append(end)
            return dates
        if interval == "monthly":
            dates = []
            d = start
            while True:
                next_month = (d.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
                month_end = next_month - datetime.timedelta(days=1)
                if month_end >= end:
                    dates.append(end)
                    break
                dates.append(month_end)
                d = next_month
            return dates
        raise ValueError("interval must be 'daily', 'weekly', or 'monthly'.")

    def holdings_history(
        self,
        portfolio: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        interval: str = "monthly",
    ) -> Dict[str, Any]:
        """Value history (portfolio valuation) across multiple dates, for charts.

        Repeats `holdings` for a series of dates between date_from and
        date_to (inclusive). Without date_from, the date of the first
        transaction is used; without date_to, today's date. Returns only the
        totals per currency for each date (no individual positions) – use
        get_holdings for individual positions on a specific date.
        """
        data = self._ensure_loaded()
        pf_uuid = self._resolve(portfolio, data["portfolios"]) if portfolio else None

        tx_dates = [t["date"].date() for t in data["transactions"] if t.get("date")]
        start = (
            datetime.date.fromisoformat(date_from) if date_from
            else (min(tx_dates) if tx_dates else datetime.date.today())
        )
        end = datetime.date.fromisoformat(date_to) if date_to else datetime.date.today()

        sample_dates = self._sample_dates(start, end, interval)
        sec_by_uuid = {s["uuid"]: s for s in data["securities"]}

        points: List[Dict[str, Any]] = []
        for d in sample_dates:
            bal = self._share_balances(pf_uuid, d)
            totals: Dict[str, Decimal] = defaultdict(lambda: Decimal(0))
            for sec_uuid, shares in bal.items():
                if shares == 0:
                    continue
                s = sec_by_uuid.get(sec_uuid)
                if s is None:
                    continue
                close, _, _ = self._price_asof(s, d)
                if close is not None:
                    totals[s.get("currencyCode")] += shares * close
            points.append({
                "date": d.isoformat(),
                "totalsByCurrency": {c: str(v) for c, v in sorted(totals.items())},
            })

        return _serialize({
            "portfolio": portfolio,
            "interval": interval,
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "baseCurrency": data["baseCurrency"],
            "pointCount": len(points),
            "points": points,
        })

    # -------------------------------------------------- gains (cost basis)
    @staticmethod
    def _fee_tax_sum(t: dict) -> Decimal:
        """Sum of the fee/tax units of a transaction."""
        return sum(
            (u["amount"] for u in t.get("units", []) if u["type"] in ("FEE", "TAX")),
            Decimal(0),
        )

    def _cost_pools(self, as_of: Optional[datetime.date]):
        """Builds a cost-basis pool per (portfolio, security) using the
        moving-average-price method (as PP does by default), logging each
        sale as a realized-gain event along the way.

        Processes transactions chronologically up to and including `as_of`
        (or all, if None). PURCHASE/INBOUND_DELIVERY increase share count and
        cost basis; SALE/OUTBOUND_DELIVERY reduce them proportionally at the
        current average price and generate a realization event;
        SECURITY_TRANSFER moves share count + cost basis proportionally
        between the portfolio pools (no gain event). For each amount, both
        the "with fees/taxes" and "without" variant are tracked: `amount` is
        already fee-inclusive for PURCHASE, and already net thereof for SALE.

        Returns (pools, events); pools: Dict[(portfolioUuid, securityUuid) -> dict
        with shares/costFee/costNoFee]; events: list of realized sales.
        """
        data = self._ensure_loaded()
        txs = [
            t for t in data["transactions"]
            if t.get("securityUuid") and t.get("date")
            and (as_of is None or t["date"].date() <= as_of)
        ]
        txs.sort(key=lambda t: t["date"])

        def new_pool():
            return {"shares": Decimal(0), "costFee": Decimal(0), "costNoFee": Decimal(0)}

        pools: Dict[Any, dict] = defaultdict(new_pool)
        events: List[Dict[str, Any]] = []

        for t in txs:
            sec = t["securityUuid"]
            shares = t.get("shares") or Decimal(0)
            if not shares:
                continue
            typ = t["type"]
            pf = t.get("portfolioUuid")

            if typ in ("PURCHASE", "INBOUND_DELIVERY"):
                fee_tax = self._fee_tax_sum(t)
                pool = pools[(pf, sec)]
                pool["shares"] += shares
                pool["costFee"] += t["amount"]
                pool["costNoFee"] += t["amount"] - fee_tax

            elif typ in ("SALE", "OUTBOUND_DELIVERY"):
                fee_tax = self._fee_tax_sum(t)
                proceeds_fee = t["amount"]            # already net (fees/taxes deducted)
                proceeds_nofee = t["amount"] + fee_tax  # gross proceeds
                pool = pools[(pf, sec)]
                if pool["shares"] > 0:
                    sold = min(shares, pool["shares"])
                    ratio = sold / pool["shares"]
                    cost_fee = pool["costFee"] * ratio
                    cost_nofee = pool["costNoFee"] * ratio
                    pool["shares"] -= sold
                    pool["costFee"] -= cost_fee
                    pool["costNoFee"] -= cost_nofee
                    events.append({
                        "date": t["date"].date(),
                        "securityUuid": sec,
                        "portfolioUuid": pf,
                        "shares": sold,
                        "proceedsWithFees": proceeds_fee,
                        "proceedsWithoutFees": proceeds_nofee,
                        "costWithFees": cost_fee,
                        "costWithoutFees": cost_nofee,
                        "gainWithFees": proceeds_fee - cost_fee,
                        "gainWithoutFees": proceeds_nofee - cost_nofee,
                    })

            elif typ == "SECURITY_TRANSFER":
                src = pools[(pf, sec)]
                if src["shares"] <= 0:
                    continue
                moved = min(shares, src["shares"])
                ratio = moved / src["shares"]
                cost_fee = src["costFee"] * ratio
                cost_nofee = src["costNoFee"] * ratio
                src["shares"] -= moved
                src["costFee"] -= cost_fee
                src["costNoFee"] -= cost_nofee
                tgt = pools[(t.get("otherPortfolioUuid"), sec)]
                tgt["shares"] += moved
                tgt["costFee"] += cost_fee
                tgt["costNoFee"] += cost_nofee

        return pools, events

    def unrealized_gains(
        self,
        portfolio: Optional[str] = None,
        date: Optional[str] = None,
        include_empty: bool = False,
        security: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Unrealized price gain per position: current value minus cost basis
        (moving average price), with and without fees/taxes.
        """
        data = self._ensure_loaded()
        pf_uuid = self._resolve(portfolio, data["portfolios"]) if portfolio else None
        sec_uuid_filter = self._find_security(security)["uuid"] if security else None
        as_of = datetime.date.fromisoformat(date) if date else None
        pools, _ = self._cost_pools(as_of)
        sec_by_uuid = {s["uuid"]: s for s in data["securities"]}

        agg: Dict[str, dict] = defaultdict(lambda: {
            "shares": Decimal(0), "costFee": Decimal(0), "costNoFee": Decimal(0)
        })
        for (pf, sec), pool in pools.items():
            if pf_uuid and pf != pf_uuid:
                continue
            if sec_uuid_filter and sec != sec_uuid_filter:
                continue
            a = agg[sec]
            a["shares"] += pool["shares"]
            a["costFee"] += pool["costFee"]
            a["costNoFee"] += pool["costNoFee"]

        positions: List[Dict[str, Any]] = []
        totals_fee: Dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        totals_nofee: Dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        missing_price = 0
        for sec_uuid, a in agg.items():
            shares = a["shares"]
            if shares == 0 and not include_empty:
                continue
            s = sec_by_uuid.get(sec_uuid)
            if s is None:
                continue
            close, price_date, source = self._price_asof(s, as_of)
            currency = s.get("currencyCode")
            value = shares * close if close is not None else None
            gain_fee = gain_nofee = None
            if value is not None:
                gain_fee = value - a["costFee"]
                gain_nofee = value - a["costNoFee"]
                totals_fee[currency] += gain_fee
                totals_nofee[currency] += gain_nofee
            else:
                missing_price += 1
            positions.append({
                "uuid": sec_uuid,
                "name": s.get("name"),
                "isin": s.get("isin"),
                "currencyCode": currency,
                "shares": shares,
                "avgCostPerShareWithFees": (a["costFee"] / shares) if shares else None,
                "avgCostPerShareWithoutFees": (a["costNoFee"] / shares) if shares else None,
                "costBasisWithFees": a["costFee"],
                "costBasisWithoutFees": a["costNoFee"],
                "price": close,
                "priceDate": price_date,
                "priceSource": source,
                "value": value,
                "unrealizedGainWithFees": gain_fee,
                "unrealizedGainWithoutFees": gain_nofee,
            })

        positions.sort(key=lambda p: (p["value"] is None, -(p["value"] or Decimal(0))))

        notes = [
            "Cost basis using the moving-average-price method (PP default), "
            "not FIFO."
        ]
        if len(totals_fee) > 1:
            notes.append("Multiple currencies – totals kept separate per currency, no conversion.")
        if missing_price:
            notes.append(f"No price available on the requested date for {missing_price} position(s) (value=null).")

        return _serialize({
            "portfolio": portfolio,
            "valuationDate": date,
            "baseCurrency": data["baseCurrency"],
            "positionCount": len(positions),
            "totalsByCurrency": {
                "withFees": {c: str(v) for c, v in sorted(totals_fee.items())},
                "withoutFees": {c: str(v) for c, v in sorted(totals_nofee.items())},
            },
            "positions": positions,
            "note": " ".join(notes),
        })

    def realized_gains(
        self,
        portfolio: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        security: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Realized price gain per security from sales (SALE/OUTBOUND_DELIVERY)
        within the period, with and without fees/taxes (moving average price).
        """
        data = self._ensure_loaded()
        pf_uuid = self._resolve(portfolio, data["portfolios"]) if portfolio else None
        sec_uuid_filter = self._find_security(security)["uuid"] if security else None
        df = datetime.date.fromisoformat(date_from) if date_from else None
        dt = datetime.date.fromisoformat(date_to) if date_to else None
        _, events = self._cost_pools(dt)
        sec_by_uuid = {s["uuid"]: s for s in data["securities"]}

        agg: Dict[str, dict] = defaultdict(lambda: {
            "shares": Decimal(0),
            "proceedsFee": Decimal(0), "proceedsNoFee": Decimal(0),
            "costFee": Decimal(0), "costNoFee": Decimal(0),
            "gainFee": Decimal(0), "gainNoFee": Decimal(0),
        })
        count = 0
        for ev in events:
            if pf_uuid and ev["portfolioUuid"] != pf_uuid:
                continue
            if sec_uuid_filter and ev["securityUuid"] != sec_uuid_filter:
                continue
            if df and ev["date"] < df:
                continue
            a = agg[ev["securityUuid"]]
            a["shares"] += ev["shares"]
            a["proceedsFee"] += ev["proceedsWithFees"]
            a["proceedsNoFee"] += ev["proceedsWithoutFees"]
            a["costFee"] += ev["costWithFees"]
            a["costNoFee"] += ev["costWithoutFees"]
            a["gainFee"] += ev["gainWithFees"]
            a["gainNoFee"] += ev["gainWithoutFees"]
            count += 1

        positions: List[Dict[str, Any]] = []
        totals_fee: Dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        totals_nofee: Dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        for sec_uuid, a in agg.items():
            s = sec_by_uuid.get(sec_uuid)
            currency = s.get("currencyCode") if s else None
            totals_fee[currency] += a["gainFee"]
            totals_nofee[currency] += a["gainNoFee"]
            positions.append({
                "uuid": sec_uuid,
                "name": s.get("name") if s else None,
                "isin": s.get("isin") if s else None,
                "currencyCode": currency,
                "sharesSold": a["shares"],
                "proceedsWithFees": a["proceedsFee"],
                "proceedsWithoutFees": a["proceedsNoFee"],
                "costBasisWithFees": a["costFee"],
                "costBasisWithoutFees": a["costNoFee"],
                "realizedGainWithFees": a["gainFee"],
                "realizedGainWithoutFees": a["gainNoFee"],
            })

        positions.sort(key=lambda p: -(p["realizedGainWithFees"] or Decimal(0)))

        notes = [
            "Cost basis using the moving-average-price method (PP default), "
            "not FIFO."
        ]
        if len(totals_fee) > 1:
            notes.append("Multiple currencies – totals kept separate per currency, no conversion.")

        return _serialize({
            "portfolio": portfolio,
            "date_from": date_from,
            "date_to": date_to,
            "baseCurrency": data["baseCurrency"],
            "saleCount": count,
            "positionCount": len(positions),
            "totalsByCurrency": {
                "withFees": {c: str(v) for c, v in sorted(totals_fee.items())},
                "withoutFees": {c: str(v) for c, v in sorted(totals_nofee.items())},
            },
            "positions": positions,
            "note": " ".join(notes),
        })

    # ------------------------------------------------------- account balance
    # Transaction types that directly change the account balance (sign from
    # the perspective of the account referenced via accountUuid). CASH_TRANSFER
    # is handled separately (source -, target +, via otherAccountUuid).
    # INBOUND_/OUTBOUND_DELIVERY and SECURITY_TRANSFER only affect portfolios,
    # not the account.
    _CASH_SIGN = {
        "DEPOSIT": Decimal(1),
        "REMOVAL": Decimal(-1),
        "DIVIDEND": Decimal(1),
        "INTEREST": Decimal(1),
        "INTEREST_CHARGE": Decimal(-1),
        "TAX_REFUND": Decimal(1),
        "TAX": Decimal(-1),
        "FEE_REFUND": Decimal(1),
        "FEE": Decimal(-1),
        "SALE": Decimal(1),
        "PURCHASE": Decimal(-1),
    }

    def account_balance(self, account: str, date: Optional[str] = None) -> Dict[str, Any]:
        """Account balance of a settlement account as of a given date.

        Sums all account-affecting transactions up to and including `date`
        (without one: all). `amount` for PURCHASE/SALE/DIVIDEND is already
        the full cash-movement amount (fees/taxes are already accounted for
        as `units`, no additional offsetting needed). CASH_TRANSFER affects
        two accounts: source (accountUuid) -, target (otherAccountUuid) +.
        """
        data = self._ensure_loaded()
        acc_uuid = self._resolve(account, data["accounts"])
        if acc_uuid is None:
            raise ValueError("No account specified.")
        as_of = datetime.date.fromisoformat(date) if date else None
        acc = next(a for a in data["accounts"] if a["uuid"] == acc_uuid)

        balance = Decimal(0)
        count = 0
        for t in data["transactions"]:
            d = t["date"].date() if t.get("date") else None
            if as_of and (d is None or d > as_of):
                continue
            typ = t["type"]
            amount = t.get("amount") or Decimal(0)
            if typ == "CASH_TRANSFER":
                if t.get("accountUuid") == acc_uuid:
                    balance -= amount
                    count += 1
                elif t.get("otherAccountUuid") == acc_uuid:
                    balance += amount
                    count += 1
            elif typ in self._CASH_SIGN:
                if t.get("accountUuid") != acc_uuid:
                    continue
                balance += self._CASH_SIGN[typ] * amount
                count += 1

        return _serialize({
            "account": account,
            "accountName": acc["name"],
            "currencyCode": acc["currencyCode"],
            "asOf": date,
            "balance": balance,
            "transactionCount": count,
        })

    # -------------------------------------------------- taxonomies / allocation
    def _resolve_taxonomy(self, data: dict, identifier: Optional[str]) -> dict:
        """Resolves a taxonomy by name or UUID (case-insensitive).

        Without `identifier`, only allowed if exactly one taxonomy exists.
        """
        taxonomies = data.get("taxonomies", [])
        if not taxonomies:
            raise ValueError("No taxonomies present in this file.")
        if identifier is None:
            if len(taxonomies) == 1:
                return taxonomies[0]
            raise ValueError(
                "Multiple taxonomies present, please specify taxonomy: "
                + ", ".join(t["name"] for t in taxonomies)
            )
        ident = identifier.strip().lower()
        for t in taxonomies:
            if t["id"].lower() == ident or t["name"].lower() == ident:
                return t
        raise ValueError(
            f"Taxonomy '{identifier}' not found. Available: "
            + ", ".join(t["name"] for t in taxonomies)
        )

    def list_taxonomies(self) -> Any:
        """All taxonomies (classification trees, e.g. asset categories,
        regions, industries) with their classifications and the assigned
        securities/accounts. `weight` is the PP-internal weighting on a
        0..10000 scale (10000 = 100%) – for classifications the target
        weight, for assignments the share of the security/account in this
        classification (usually 10000, except for split assignments).
        """
        data = self._ensure_loaded()

        def vehicle_name(uuid: str) -> Optional[str]:
            return self._security_names.get(uuid) or self._account_names.get(uuid)

        result = []
        for tax in data["taxonomies"]:
            classifications = []
            for c in tax["classifications"]:
                classifications.append({
                    "id": c["id"],
                    "parentId": c["parentId"],
                    "name": c["name"],
                    "color": c["color"],
                    "weight": c["weight"],
                    "assignments": [
                        {
                            "vehicleUuid": a["investmentVehicleUuid"],
                            "vehicleName": vehicle_name(a["investmentVehicleUuid"]),
                            "weight": a["weight"],
                        }
                        for a in c["assignments"]
                    ],
                })
            result.append({
                "id": tax["id"],
                "name": tax["name"],
                "dimensions": tax["dimensions"],
                "classifications": classifications,
            })
        return _serialize(result)

    def asset_allocation(
        self,
        taxonomy: Optional[str] = None,
        date: Optional[str] = None,
        portfolio: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Portfolio allocation according to a taxonomy (e.g. asset
        categories, regions, industries): distributes the current holdings
        value of securities (and – only without a `portfolio` filter –
        balances of assigned settlement accounts, e.g. for "cash") across a
        given date according to the classification assignment stored in
        Portfolio Performance.

        Without `taxonomy`, the single existing taxonomy is used (with
        multiple taxonomies, specifying name or UUID is mandatory, see
        `list_taxonomies`). Securities/accounts without an assignment in this
        taxonomy end up under "Unclassified". No FX conversion – totals per
        currency.
        """
        data = self._ensure_loaded()
        tax = self._resolve_taxonomy(data, taxonomy)
        pf_uuid = self._resolve(portfolio, data["portfolios"]) if portfolio else None
        as_of = datetime.date.fromisoformat(date) if date else None

        class_by_id = {c["id"]: c for c in tax["classifications"]}
        vehicle_assignments: Dict[str, List[tuple]] = defaultdict(list)
        for c in tax["classifications"]:
            for a in c["assignments"]:
                w = Decimal(a["weight"]) / Decimal(10000)
                if w > 0:
                    vehicle_assignments[a["investmentVehicleUuid"]].append((c["id"], w))

        UNCLASSIFIED = "__unclassified__"
        totals: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal(0)))

        bal = self._share_balances(pf_uuid, as_of)
        sec_by_uuid = {s["uuid"]: s for s in data["securities"]}
        missing_price = 0
        for sec_uuid, shares in bal.items():
            if shares == 0:
                continue
            s = sec_by_uuid.get(sec_uuid)
            if s is None:
                continue
            close, _, _ = self._price_asof(s, as_of)
            if close is None:
                missing_price += 1
                continue
            value = shares * close
            currency = s.get("currencyCode")
            assigns = vehicle_assignments.get(sec_uuid)
            if assigns:
                for class_id, w in assigns:
                    totals[class_id][currency] += value * w
            else:
                totals[UNCLASSIFIED][currency] += value

        # Only include account balances when not filtered by portfolio
        # (settlement accounts are not uniquely assigned to portfolios).
        if pf_uuid is None:
            for acc in data["accounts"]:
                assigns = vehicle_assignments.get(acc["uuid"])
                if not assigns:
                    continue
                balance = Decimal(self.account_balance(acc["uuid"], date)["balance"])
                currency = acc["currencyCode"]
                for class_id, w in assigns:
                    totals[class_id][currency] += balance * w

        classifications_out = []
        for class_id, by_currency in totals.items():
            if class_id == UNCLASSIFIED:
                out_id, name, parent_id, color = None, "Unclassified", None, None
            else:
                c = class_by_id.get(class_id, {})
                out_id, name, parent_id, color = class_id, c.get("name"), c.get("parentId"), c.get("color")
            classifications_out.append({
                "id": out_id,
                "name": name,
                "parentId": parent_id,
                "color": color,
                "valueByCurrency": {cur: str(v) for cur, v in sorted(by_currency.items())},
            })

        classifications_out.sort(
            key=lambda c: -sum(Decimal(v) for v in c["valueByCurrency"].values())
        )

        notes = []
        if missing_price:
            notes.append(f"No price available on the requested date for {missing_price} position(s) (omitted).")

        return _serialize({
            "taxonomy": tax["name"],
            "portfolio": portfolio,
            "valuationDate": date,
            "baseCurrency": data["baseCurrency"],
            "classifications": classifications_out,
            "note": " ".join(notes) if notes else None,
        })

    # -------------------------------------------------- savings plans
    def investment_plans(self) -> Any:
        """List of savings plans/investment plans (automatic security
        purchases/sales or account deposits/withdrawals). `intervalMonths` is
        the interval between executions in months (1 = monthly, 3 =
        quarterly, …); `transactionCount` is the number of transactions
        already generated.
        """
        data = self._ensure_loaded()
        result = []
        for p in data["plans"]:
            result.append({
                "name": p["name"],
                "note": p["note"],
                "type": p["type"],
                "securityUuid": p["securityUuid"],
                "securityName": self._security_names.get(p["securityUuid"]) if p["securityUuid"] else None,
                "portfolioUuid": p["portfolioUuid"],
                "portfolioName": self._portfolio_names.get(p["portfolioUuid"]) if p["portfolioUuid"] else None,
                "accountUuid": p["accountUuid"],
                "accountName": self._account_names.get(p["accountUuid"]) if p["accountUuid"] else None,
                "autoGenerate": p["autoGenerate"],
                "startDate": p["date"],
                "intervalMonths": p["interval"],
                "amount": p["amount"],
                "fees": p["fees"],
                "taxes": p["taxes"],
                "transactionCount": p["transactionCount"],
            })
        return _serialize(result)

    def _enrich(self, t: dict) -> Dict[str, Any]:
        """Enriches a transaction with readable names and serializes it."""
        item = dict(t)
        item["accountName"] = self._account_names.get(t.get("accountUuid"))
        item["portfolioName"] = self._portfolio_names.get(t.get("portfolioUuid"))
        item["securityName"] = self._security_names.get(t.get("securityUuid"))
        item["securityIsin"] = self._security_isins.get(t.get("securityUuid"))
        return _serialize(item)

    def _filter_raw(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        types: Optional[List[str]] = None,
        account: Optional[str] = None,
        portfolio: Optional[str] = None,
        security: Optional[str] = None,
    ) -> List[dict]:
        """Internal filter, returns the raw (non-serialized) transactions."""
        data = self._ensure_loaded()

        df = datetime.date.fromisoformat(date_from) if date_from else None
        dt = datetime.date.fromisoformat(date_to) if date_to else None

        type_set = None
        if types:
            type_set = {t.strip().upper() for t in types}
            unknown = type_set - set(TRANSACTION_TYPES)
            if unknown:
                raise ValueError(
                    f"Unknown transaction type(s): {', '.join(sorted(unknown))}. "
                    f"Valid: {', '.join(TRANSACTION_TYPES)}"
                )

        account_uuid = self._resolve(account, data["accounts"])
        portfolio_uuid = self._resolve(portfolio, data["portfolios"])
        security_uuid = self._resolve(security, data["securities"])

        result = []
        for t in data["transactions"]:
            tdate = t["date"].date() if t.get("date") else None
            if df and (tdate is None or tdate < df):
                continue
            if dt and (tdate is None or tdate > dt):
                continue
            if type_set and t["type"] not in type_set:
                continue
            if account_uuid and t.get("accountUuid") != account_uuid:
                continue
            if portfolio_uuid and t.get("portfolioUuid") != portfolio_uuid:
                continue
            if security_uuid and t.get("securityUuid") != security_uuid:
                continue
            result.append(t)

        result.sort(key=lambda x: x["date"] or datetime.datetime.min)
        return result

    def filter_transactions(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        types: Optional[List[str]] = None,
        account: Optional[str] = None,
        portfolio: Optional[str] = None,
        security: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Filtered, enriched, and serialized transactions."""
        return [self._enrich(t) for t in self._filter_raw(
            date_from, date_to, types, account, portfolio, security
        )]

    def summarize(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        account: Optional[str] = None,
        portfolio: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Totals per transaction type and grand total within the period (for reports)."""
        rows = self._filter_raw(date_from, date_to, None, account, portfolio, None)
        by_type: Dict[str, Dict[str, Any]] = {}
        total = Decimal(0)
        for t in rows:
            entry = by_type.setdefault(t["type"], {"count": 0, "amount": Decimal(0)})
            entry["count"] += 1
            entry["amount"] += t["amount"]
            total += t["amount"]
        return {
            "filter": {
                "date_from": date_from,
                "date_to": date_to,
                "account": account,
                "portfolio": portfolio,
            },
            "byType": {k: {"count": v["count"], "amount": str(v["amount"])}
                       for k, v in sorted(by_type.items())},
            "totalAmount": str(total),
            "transactionCount": len(rows),
        }


def _load_sources() -> List[Dict[str, Any]]:
    """Reads the configured portfolio sources.

    If PP_PORTFOLIOS_CONFIG is set, reads that JSON file (list of
    {id, label, path, password}). Otherwise falls back to a single source
    "default" built from PP_FILE_PATH/PP_PASSWORD (single-file operation,
    e.g. a local launchd service).
    """
    if settings.PP_PORTFOLIOS_CONFIG:
        with open(settings.PP_PORTFOLIOS_CONFIG, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [
            {
                "id": entry["id"],
                "label": entry.get("label", entry["id"]),
                "path": entry["path"],
                "password": entry.get("password") or None,
            }
            for entry in raw
        ]
    return [{
        "id": "default",
        "label": "default",
        "path": settings.PP_FILE_PATH,
        "password": settings.PP_PASSWORD,
    }]


class PortfolioRegistry:
    """Manages multiple portfolio sources, one dedicated Portfolio instance
    (with its own mtime cache) per configured file."""

    def __init__(self, sources: List[Dict[str, Any]]):
        self._sources: Dict[str, Dict[str, Any]] = {s["id"]: s for s in sources}
        self._instances: Dict[str, Portfolio] = {}
        # With exactly one source, the `source` parameter in the tools is optional.
        self._default_id = sources[0]["id"] if len(sources) == 1 else None

    def list_sources(self) -> List[Dict[str, str]]:
        """Configured sources without paths/passwords (for list_data_sources)."""
        return [{"id": s["id"], "label": s.get("label", s["id"])} for s in self._sources.values()]

    def get(self, source_id: Optional[str] = None) -> Portfolio:
        if source_id is None:
            if self._default_id is None:
                if not self._sources:
                    raise PortfolioNotConfigured("No portfolio source configured.")
                raise ValueError(
                    "Multiple portfolio sources configured – please specify 'source'. "
                    f"Available: {', '.join(sorted(self._sources))}"
                )
            source_id = self._default_id
        if source_id not in self._sources:
            raise ValueError(
                f"Unknown portfolio source '{source_id}'. "
                f"Available: {', '.join(sorted(self._sources))}"
            )
        if source_id not in self._instances:
            src = self._sources[source_id]
            self._instances[source_id] = Portfolio(src["path"], src.get("password"))
        return self._instances[source_id]


# Global registry – shares the cache across all tool calls
registry = PortfolioRegistry(_load_sources())
