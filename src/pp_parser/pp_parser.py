import io
import zipfile
import struct
import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List

try:
    from Crypto.Protocol.KDF import PBKDF2
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    from Crypto.Hash import SHA1
except ImportError:
    try:
        from Cryptodome.Protocol.KDF import PBKDF2
        from Cryptodome.Cipher import AES
        from Cryptodome.Util.Padding import unpad
        from Cryptodome.Hash import SHA1
    except ImportError:
        raise ImportError("Additional library 'pycryptodome' or 'pycryptodomex' was not found. "
                          "Please install it with 'pip install pycryptodome'.")

# Import generated protobuf classes
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'generated'))
try:
    import client_pb2
except ImportError:
    # Fallback if generated directory is not in path correctly
    from .generated import client_pb2

# Security constants
SALT_LENGTH = 16
KEY_LENGTH = 32
ITERATIONS = 100000

# Portfolio Performance stores prices (quotes) scaled by 10^8.
QUOTE_FACTOR = Decimal(10) ** 8

def from_decimal_value(pdv) -> Decimal:
    """Converts a PDecimalValue to Decimal."""
    if not pdv.value:
        return Decimal(0)
    unscaled = int.from_bytes(pdv.value, byteorder='big', signed=True)
    return Decimal(unscaled) / Decimal(10 ** pdv.scale)

def from_epoch_day(epoch_day: int) -> datetime.date:
    """Converts an epoch day to datetime.date."""
    # Java (and PP) use epoch day 1970-01-01
    # Python date.fromordinal(1) is 0001-01-01
    # The offset between 0001-01-01 and 1970-01-01 is 719163 days
    return datetime.date.fromordinal(epoch_day + 719163)

def from_timestamp(ts) -> datetime.datetime:
    """Converts a google.protobuf.Timestamp to datetime."""
    return datetime.datetime.fromtimestamp(ts.seconds + ts.nanos / 1e9, tz=datetime.timezone.utc)

def from_local_date_time(pldt) -> datetime.datetime:
    """Converts a PLocalDateTime to datetime."""
    date = from_epoch_day(pldt.epoch_day)
    time = datetime.time(
        pldt.second_of_day // 3600,
        (pldt.second_of_day % 3600) // 60,
        pldt.second_of_day % 60
    )
    return datetime.datetime.combine(date, time)

def decrypt_portfolio(data: bytes, password: str) -> bytes:
    """Decrypts an AES-encrypted portfolio file."""
    if not data.startswith(b"PORTFOLIO"):
        raise ValueError("Not a valid encrypted portfolio file (signature missing)")

    method = data[9] # 0 = AES128, 1 = AES256
    iv = data[10:26]
    encrypted_payload = data[26:]

    key_len = 16 if method == 0 else 32

    # Hardcoded salt (signed bytes in Java -> unsigned in Python)
    # [112, 67, 103, 107, -92, -125, -112, -95, -97, -114, 117, -56, -53, -69, -25, -28]
    salt = bytes([112, 67, 103, 107, 164, 131, 144, 161, 159, 142, 117, 200, 203, 187, 231, 228])

    key = PBKDF2(password, salt, dkLen=key_len, count=65536, hmac_hash_module=SHA1)

    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(encrypted_payload), AES.block_size)

    # Decrypted structure:
    # Content-Type (4 bytes Big-Endian)
    # Version (4 bytes Big-Endian)
    # ZIP data
    content_type = struct.unpack(">I", decrypted[0:4])[0]
    # version = struct.unpack(">I", decrypted[4:8])[0]
    zip_data = decrypted[8:]

    if content_type != 2:
        raise ValueError(f"Unexpected content type after decryption: {content_type} (expected 2 for protobuf)")

    return zip_data

def get_protobuf_from_zip(zip_bytes: bytes) -> bytes:
    """Extracts the protobuf data from a ZIP container."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        if "data.portfolio" in zf.namelist():
            data = zf.read("data.portfolio")
        elif "data" in zf.namelist():
            data = zf.read("data")
        else:
            raise ValueError("No 'data.portfolio' or 'data' file found in the ZIP container")

    if data.startswith(b"PPPBV1"):
        return data[6:]
    return data

def parse_portfolio_file(filepath: str, password: str = None) -> dict:
    """Reads a .portfolio file (XML or binary) and returns a dict."""
    with open(filepath, "rb") as f:
        header = f.read(9)
        f.seek(0)
        file_data = f.read()

    if header.startswith(b"PK\x03\x04"):
        # Unencrypted ZIP
        proto_bytes = get_protobuf_from_zip(file_data)
    elif header.startswith(b"PORTFOLIO"):
        # Encrypted
        if not password:
            raise ValueError("File is encrypted, but no password was provided")
        zip_data = decrypt_portfolio(file_data, password)
        proto_bytes = get_protobuf_from_zip(zip_data)
    elif header.startswith(b"<?xml"):
        raise ValueError("XML format is not (yet) supported by this parser. Please use an XML parser.")
    else:
        raise ValueError("Unknown file format")

    client = client_pb2.PClient()
    client.ParseFromString(proto_bytes)

    result = {
        "version": client.version,
        "baseCurrency": client.baseCurrency,
        "securities": [],
        "accounts": [],
        "portfolios": [],
        "transactions": [],
        "taxonomies": [],
        "plans": [],
    }

    # Securities
    for s in client.securities:
        sec_dict = {
            "uuid": s.uuid,
            "name": s.name,
            "isin": s.isin if s.HasField("isin") else None,
            "tickerSymbol": s.tickerSymbol if s.HasField("tickerSymbol") else None,
            "wkn": s.wkn if s.HasField("wkn") else None,
            "currencyCode": s.currencyCode if s.HasField("currencyCode") else None,
            "isRetired": s.isRetired,
            "feed": s.feed if s.HasField("feed") else None,
            "feedURL": s.feedURL if s.HasField("feedURL") else None,
            "latestFeed": s.latestFeed if s.HasField("latestFeed") else None,
            "latestFeedURL": s.latestFeedURL if s.HasField("latestFeedURL") else None,
            "prices": [],
            "latest": None,
            "events": [],
        }
        for p in s.prices:
            sec_dict["prices"].append({
                "date": from_epoch_day(p.date),
                "close": Decimal(p.close) / QUOTE_FACTOR
            })
        # Most recent price (a separate field in PP, often newer than the last historical price).
        # high/low/volume are -1 or 0, respectively, when not present.
        if s.HasField("latest"):
            L = s.latest
            sec_dict["latest"] = {
                "date": from_epoch_day(L.date),
                "close": Decimal(L.close) / QUOTE_FACTOR,
                "high": Decimal(L.high) / QUOTE_FACTOR if L.high > 0 else None,
                "low": Decimal(L.low) / QUOTE_FACTOR if L.low > 0 else None,
                "volume": L.volume if L.volume > 0 else None,
            }
        for e in s.events:
            event_type = client_pb2.PSecurityEvent.Type.Name(e.type)
            event_dict = {
                "type": event_type,
                "date": from_epoch_day(e.date),
                "details": e.details,
            }
            if e.type == client_pb2.PSecurityEvent.DIVIDEND_PAYMENT and len(e.data) >= 3:
                # data[0].int64 = payment date, data[1].string = currency, data[2].int64 = amount
                event_dict["paymentDate"] = from_epoch_day(e.data[0].int64)
                event_dict["currencyCode"] = e.data[1].string
                event_dict["amount"] = Decimal(e.data[2].int64) / 100
            sec_dict["events"].append(event_dict)
        result["securities"].append(sec_dict)

    # Accounts
    for a in client.accounts:
        result["accounts"].append({
            "uuid": a.uuid,
            "name": a.name,
            "currencyCode": a.currencyCode,
            "isRetired": a.isRetired,
        })

    # Portfolios
    for p in client.portfolios:
        result["portfolios"].append({
            "uuid": p.uuid,
            "name": p.name,
            "referenceAccountUuid": p.referenceAccount if p.HasField("referenceAccount") else None,
            "isRetired": p.isRetired,
        })

    # Transactions
    for t in client.transactions:
        trans_dict = {
            "uuid": t.uuid,
            "type": client_pb2.PTransaction.Type.Name(t.type),
            "date": from_timestamp(t.date),
            "amount": Decimal(t.amount) / 100,
            "shares": Decimal(t.shares) / 100_000_000 if t.HasField("shares") else None,
            "currencyCode": t.currencyCode,
            "securityUuid": t.security if t.HasField("security") else None,
            "accountUuid": t.account if t.HasField("account") else None,
            "portfolioUuid": t.portfolio if t.HasField("portfolio") else None,
            "otherAccountUuid": t.otherAccount if t.HasField("otherAccount") else None,
            "otherPortfolioUuid": t.otherPortfolio if t.HasField("otherPortfolio") else None,
            "note": t.note if t.HasField("note") else None,
            "units": [],
        }
        if t.HasField("exDate"):
            trans_dict["exDate"] = from_local_date_time(t.exDate)

        for u in t.units:
            unit_dict = {
                "type": client_pb2.PTransactionUnit.Type.Name(u.type),
                "amount": Decimal(u.amount) / 100,
                "currencyCode": u.currencyCode,
            }
            if u.HasField("fxAmount"):
                unit_dict["fxAmount"] = Decimal(u.fxAmount) / 100
            if u.HasField("fxCurrencyCode"):
                unit_dict["fxCurrencyCode"] = u.fxCurrencyCode
            trans_dict["units"].append(unit_dict)
        result["transactions"].append(trans_dict)

    # Taxonomies (classification trees, e.g. asset classes, regions, industries)
    for tax in client.taxonomies:
        classifications = []
        for c in tax.classifications:
            classifications.append({
                "id": c.id,
                "parentId": c.parentId or None,
                "name": c.name,
                "color": c.color or None,
                "weight": c.weight,
                "rank": c.rank,
                "assignments": [
                    {
                        "investmentVehicleUuid": a.investmentVehicle,
                        "weight": a.weight,
                        "rank": a.rank,
                    }
                    for a in c.assignments
                ],
            })
        result["taxonomies"].append({
            "id": tax.id,
            "name": tax.name,
            "dimensions": list(tax.dimensions),
            "classifications": classifications,
        })

    # Savings plans / investment plans
    for p in client.plans:
        result["plans"].append({
            "name": p.name,
            "note": p.note if p.HasField("note") else None,
            "type": client_pb2.PInvestmentPlan.Type.Name(p.type),
            "securityUuid": p.security if p.HasField("security") else None,
            "portfolioUuid": p.portfolio if p.HasField("portfolio") else None,
            "accountUuid": p.account if p.HasField("account") else None,
            "autoGenerate": p.autoGenerate,
            "date": from_epoch_day(p.date),
            "interval": p.interval,
            "amount": Decimal(p.amount) / 100,
            "fees": Decimal(p.fees) / 100,
            "taxes": Decimal(p.taxes) / 100,
            "transactionCount": len(p.transactions),
        })

    return result
