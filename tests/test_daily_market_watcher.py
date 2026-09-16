import csv
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import daily_market_watcher as watcher


class FetchLatestTests(unittest.TestCase):
    @patch("daily_market_watcher.yf.Ticker")
    def test_fetch_latest_includes_three_month_reference(self, mock_ticker):
        dates = pd.date_range("2026-01-01", periods=100, freq="D")
        closes = pd.Series(list(range(1, 101)), index=dates)
        mock_ticker.return_value.history.return_value = pd.DataFrame({"Close": closes})

        latest, prev, five_day_close, month_close, quarter_close = watcher.fetch_latest("TEST")

        self.assertEqual(latest, 100.0)
        self.assertEqual(prev, 99.0)
        self.assertEqual(five_day_close, 95.0)
        self.assertEqual(month_close, 79.0)
        self.assertEqual(quarter_close, 10.0)

    @patch("daily_market_watcher.yf.Ticker")
    def test_fetch_latest_falls_back_to_latest_prior_row_for_three_month_reference(self, mock_ticker):
        dates = pd.date_range("2026-01-01", "2026-04-10", freq="D").delete(9)
        closes = pd.Series(list(range(1, len(dates) + 1)), index=dates)
        mock_ticker.return_value.history.return_value = pd.DataFrame({"Close": closes})

        *_, quarter_close = watcher.fetch_latest("TEST")

        self.assertEqual(quarter_close, 9.0)

    @patch("daily_market_watcher.yf.Ticker")
    def test_fetch_latest_returns_missing_three_month_reference_when_no_earlier_history_exists(self, mock_ticker):
        dates = pd.date_range("2026-03-20", periods=10, freq="D")
        closes = pd.Series(list(range(1, 11)), index=dates)
        mock_ticker.return_value.history.return_value = pd.DataFrame({"Close": closes})

        latest, prev, five_day_close, month_close, quarter_close = watcher.fetch_latest("TEST")

        self.assertEqual(latest, 10.0)
        self.assertEqual(prev, 9.0)
        self.assertEqual(five_day_close, 5.0)
        self.assertIsNone(month_close)
        self.assertIsNone(quarter_close)


class AppendCsvRowTests(unittest.TestCase):
    def test_schema_expansion_ignores_extra_values_and_pads_short_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/market.csv"
            with open(path, "w", newline="", encoding="utf-8") as handle:
                handle.write("date,copper\n2026-01-01,100,legacy-extra\n2026-01-02,101\n")

            watcher.append_csv_row(path, {"date": "2026-01-03", "copper": "102", "iron": "120"})

            with open(path, newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows, [
                ["date", "copper", "iron"],
                ["2026-01-01", "100", ""],
                ["2026-01-02", "101", ""],
                ["2026-01-03", "102", "120"],
            ])

    def test_append_unique_csv_rows_fills_missing_values_for_existing_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/market.csv"
            with open(path, "w", newline="", encoding="utf-8") as handle:
                handle.write("日時,copper,iron\n2026-01-01,100,\n")

            watcher.append_unique_csv_rows(
                path,
                [{"日時": "2026-01-01", "copper": "101", "iron": "120"}],
                fieldnames=["日時", "copper", "iron"],
            )

            with open(path, newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows, [
                ["日時", "copper", "iron"],
                ["2026-01-01", "100", "120"],
            ])


if __name__ == "__main__":
    unittest.main()
