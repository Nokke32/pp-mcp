import datetime
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path

from src.portfolio import Portfolio
from src.pp_parser import parse_portfolio_file
from src.pp_parser.generated import client_pb2


class AccountBalanceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.portfolio_path = Path(self.temp_dir.name) / "test.portfolio"
        self._write_portfolio()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_portfolio(self):
        client = client_pb2.PClient()

        source = client.accounts.add()
        source.uuid = "source"
        source.name = "Source USD"
        source.currencyCode = "USD"

        target = client.accounts.add()
        target.uuid = "target"
        target.name = "Target JPY"
        target.currencyCode = "JPY"

        transfer = client.transactions.add()
        transfer.uuid = "transfer"
        transfer.type = client_pb2.PTransaction.CASH_TRANSFER
        transfer.account = source.uuid
        transfer.otherAccount = target.uuid
        transfer.date.FromDatetime(
            datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
        )
        transfer.currencyCode = "USD"
        transfer.amount = 10_000

        gross_value = transfer.units.add()
        gross_value.type = client_pb2.PTransactionUnit.GROSS_VALUE
        gross_value.currencyCode = "USD"
        gross_value.amount = 10_000
        gross_value.fxCurrencyCode = "JPY"
        gross_value.fxAmount = 1_427_300

        deposit = client.transactions.add()
        deposit.uuid = "deposit"
        deposit.type = client_pb2.PTransaction.DEPOSIT
        deposit.account = target.uuid
        deposit.date.FromDatetime(
            datetime.datetime(2026, 2, 10, tzinfo=datetime.timezone.utc)
        )
        deposit.currencyCode = "JPY"
        deposit.amount = 20_000

        with zipfile.ZipFile(self.portfolio_path, "w") as archive:
            archive.writestr("data.portfolio", b"PPPBV1" + client.SerializeToString())

    def test_parser_preserves_forex_amount(self):
        data = parse_portfolio_file(str(self.portfolio_path))

        gross_value = data["transactions"][0]["units"][0]
        self.assertEqual(Decimal("14273"), gross_value["fxAmount"])
        self.assertEqual("JPY", gross_value["fxCurrencyCode"])

    def test_cross_currency_transfer_uses_each_accounts_currency(self):
        portfolio = Portfolio(str(self.portfolio_path))

        source = portfolio.account_balance("Source USD")
        target = portfolio.account_balance("Target JPY")
        target_at_transfer = portfolio.account_balance("Target JPY", "2026-01-10")

        self.assertEqual("-100", source["balance"])
        self.assertEqual("14473", target["balance"])
        self.assertEqual(2, target["transactionCount"])
        self.assertEqual("14273", target_at_transfer["balance"])
        self.assertEqual(1, target_at_transfer["transactionCount"])


if __name__ == "__main__":
    unittest.main()
