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


if __name__ == "__main__":
    unittest.main()
