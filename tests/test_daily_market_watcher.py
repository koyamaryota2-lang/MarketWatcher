import csv
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import daily_market_watcher as watcher


class FetchLatestTests(unittest.TestCase):
    @patch("daily_market_watcher.yf.Ticker")
    def test_fetch_latest_includes_three_month_reference(self, mock_ticker):
        closes = pd.Series(list(range(1, 80)))
        mock_ticker.return_value.history.return_value = pd.DataFrame({"Close": closes})

        latest, prev, five_day_close, month_close, quarter_close = watcher.fetch_latest("TEST")

        self.assertEqual(latest, 79.0)
        self.assertEqual(prev, 78.0)
        self.assertEqual(five_day_close, 74.0)
        self.assertEqual(month_close, 58.0)
        self.assertEqual(quarter_close, 14.0)


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


if __name__ == "__main__":
    unittest.main()
