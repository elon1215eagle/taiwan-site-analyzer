from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tw_site_analyzer.pos_data import PosDataValidationError, load_pos_daily_csv


class PosDataTest(unittest.TestCase):
    def write_csv(self, content: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "ichef.csv"
        path.write_text(content, encoding="utf-8-sig")
        return path

    def test_normalized_daily_sales_calculates_actual_ticket(self):
        path = self.write_csv(
            "store_id,store_name,business_date,business_type,net_sales,completed_orders,guest_count\n"
            "KH001,LAIGDO 建工店,2026-07-29,炸雞,12000,100,80\n"
            "KH002,LAIGDO 左營店,2026-07-29,炸雞,18000,120,100\n"
        )

        records, summary = load_pos_daily_csv(path)

        self.assertEqual(len(records), 2)
        self.assertEqual(summary.store_count, 2)
        self.assertEqual(summary.total_net_sales, 30000)
        self.assertEqual(summary.total_completed_orders, 220)
        self.assertEqual(summary.actual_average_order_value, 136.36)
        self.assertEqual(summary.actual_average_guest_spend, 166.67)

    def test_chinese_headers_are_supported(self):
        path = self.write_csv(
            "門市代碼,門市名稱,營業日,業態,營業淨額,完成訂單數\n"
            "KH001,LAIGDO 建工店,2026-07-29,炸雞,\"12,000\",100\n"
        )

        records, summary = load_pos_daily_csv(path)

        self.assertEqual(records[0].net_sales, 12000)
        self.assertEqual(summary.actual_average_order_value, 120)

    def test_duplicate_store_day_is_rejected(self):
        path = self.write_csv(
            "store_id,store_name,business_date,business_type,net_sales,completed_orders\n"
            "KH001,LAIGDO 建工店,2026-07-29,炸雞,12000,100\n"
            "KH001,LAIGDO 建工店,2026-07-29,炸雞,13000,110\n"
        )

        with self.assertRaises(PosDataValidationError) as context:
            load_pos_daily_csv(path)

        self.assertIn("同一門市與營業日重複", str(context.exception))

    def test_sales_without_orders_is_rejected(self):
        path = self.write_csv(
            "store_id,store_name,business_date,business_type,net_sales,completed_orders\n"
            "KH001,LAIGDO 建工店,2026-07-29,炸雞,12000,0\n"
        )

        with self.assertRaises(PosDataValidationError) as context:
            load_pos_daily_csv(path)

        self.assertIn("完成訂單數為 0", str(context.exception))


if __name__ == "__main__":
    unittest.main()
