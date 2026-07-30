from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELD_ALIASES = {
    "store_id": ("store_id", "門市代碼", "分店代碼"),
    "store_name": ("store_name", "門市名稱", "分店名稱"),
    "business_date": ("business_date", "營業日", "日期"),
    "business_type": ("business_type", "業態", "品牌業態"),
    "net_sales": ("net_sales", "營業淨額", "淨營業額"),
    "completed_orders": ("completed_orders", "完成訂單數", "訂單數"),
    "guest_count": ("guest_count", "來客數", "消費人數"),
    "discount_amount": ("discount_amount", "折扣金額", "折讓金額"),
    "refund_amount": ("refund_amount", "退款金額", "退貨金額"),
    "dine_in_sales": ("dine_in_sales", "內用營業額"),
    "takeout_sales": ("takeout_sales", "外帶營業額"),
    "delivery_sales": ("delivery_sales", "外送營業額"),
}

REQUIRED_FIELDS = (
    "store_id",
    "store_name",
    "business_date",
    "business_type",
    "net_sales",
    "completed_orders",
)


class PosDataValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class PosDailyRecord:
    store_id: str
    store_name: str
    business_date: str
    business_type: str
    net_sales: float
    completed_orders: int
    guest_count: int | None = None
    discount_amount: float = 0
    refund_amount: float = 0
    dine_in_sales: float | None = None
    takeout_sales: float | None = None
    delivery_sales: float | None = None


@dataclass(frozen=True)
class PosDatasetSummary:
    row_count: int
    store_count: int
    start_date: str
    end_date: str
    total_net_sales: float
    total_completed_orders: int
    actual_average_order_value: float | None
    total_guest_count: int | None
    actual_average_guest_spend: float | None
    warnings: list[str]


def load_pos_daily_csv(path: str | Path) -> tuple[list[PosDailyRecord], PosDatasetSummary]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise PosDataValidationError([f"檔案不存在：{csv_path}"])
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise PosDataValidationError(["CSV 缺少標題列。"])
        field_map = resolve_fields(reader.fieldnames)
        missing = [field for field in REQUIRED_FIELDS if field not in field_map]
        if missing:
            raise PosDataValidationError([f"缺少必要欄位：{', '.join(missing)}"])
        records = []
        errors = []
        seen = set()
        for row_number, row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in row.values()):
                continue
            try:
                record = parse_record(row, field_map)
                key = (record.store_id, record.business_date)
                if key in seen:
                    raise ValueError("同一門市與營業日重複")
                seen.add(key)
                records.append(record)
            except ValueError as error:
                errors.append(f"第 {row_number} 列：{error}")
        if errors:
            raise PosDataValidationError(errors)
    if not records:
        raise PosDataValidationError(["CSV 沒有可匯入的營業資料。"])
    return records, summarize_dataset(records)


def resolve_fields(fieldnames: list[str]) -> dict[str, str]:
    normalized = {str(name).strip(): str(name) for name in fieldnames}
    return {
        target: normalized[alias]
        for target, aliases in FIELD_ALIASES.items()
        for alias in aliases
        if alias in normalized
    }


def parse_record(row: dict[str, str], field_map: dict[str, str]) -> PosDailyRecord:
    values = {
        field: str(row.get(source, "") or "").strip()
        for field, source in field_map.items()
    }
    for field in REQUIRED_FIELDS:
        if not values.get(field):
            raise ValueError(f"{field} 不可空白")
    try:
        parsed_date = date.fromisoformat(values["business_date"])
    except ValueError as error:
        raise ValueError("business_date 必須為 YYYY-MM-DD") from error
    net_sales = parse_non_negative_decimal(values["net_sales"], "net_sales")
    completed_orders = parse_non_negative_int(values["completed_orders"], "completed_orders")
    if net_sales > 0 and completed_orders == 0:
        raise ValueError("有營業淨額但完成訂單數為 0")
    return PosDailyRecord(
        store_id=values["store_id"],
        store_name=values["store_name"],
        business_date=parsed_date.isoformat(),
        business_type=values["business_type"],
        net_sales=net_sales,
        completed_orders=completed_orders,
        guest_count=parse_optional_int(values.get("guest_count"), "guest_count"),
        discount_amount=parse_optional_decimal(values.get("discount_amount"), "discount_amount") or 0,
        refund_amount=parse_optional_decimal(values.get("refund_amount"), "refund_amount") or 0,
        dine_in_sales=parse_optional_decimal(values.get("dine_in_sales"), "dine_in_sales"),
        takeout_sales=parse_optional_decimal(values.get("takeout_sales"), "takeout_sales"),
        delivery_sales=parse_optional_decimal(values.get("delivery_sales"), "delivery_sales"),
    )


def parse_non_negative_decimal(value: str, field: str) -> float:
    try:
        number = Decimal(value.replace(",", ""))
    except (InvalidOperation, AttributeError) as error:
        raise ValueError(f"{field} 必須是數字") from error
    if number < 0:
        raise ValueError(f"{field} 不可為負數")
    return float(number)


def parse_optional_decimal(value: str | None, field: str) -> float | None:
    if value in (None, ""):
        return None
    return parse_non_negative_decimal(value, field)


def parse_non_negative_int(value: str, field: str) -> int:
    try:
        number = int(value.replace(",", ""))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} 必須是整數") from error
    if number < 0:
        raise ValueError(f"{field} 不可為負數")
    return number


def parse_optional_int(value: str | None, field: str) -> int | None:
    if value in (None, ""):
        return None
    return parse_non_negative_int(value, field)


def summarize_dataset(records: list[PosDailyRecord]) -> PosDatasetSummary:
    total_sales = sum(record.net_sales for record in records)
    total_orders = sum(record.completed_orders for record in records)
    guest_values = [record.guest_count for record in records if record.guest_count is not None]
    total_guests = sum(guest_values) if len(guest_values) == len(records) else None
    warnings = []
    if len({record.business_type for record in records}) > 1:
        warnings.append("資料包含多種業態，建立同業態基準時必須分組。")
    if total_guests is None:
        warnings.append("部分資料缺少來客數，無法計算完整的每人客單價。")
    channel_rows = [
        record
        for record in records
        if any(
            value is not None
            for value in (record.dine_in_sales, record.takeout_sales, record.delivery_sales)
        )
    ]
    if len(channel_rows) != len(records):
        warnings.append("部分資料缺少內用、外帶或外送拆分。")
    dates = sorted(record.business_date for record in records)
    return PosDatasetSummary(
        row_count=len(records),
        store_count=len({record.store_id for record in records}),
        start_date=dates[0],
        end_date=dates[-1],
        total_net_sales=round(total_sales, 2),
        total_completed_orders=total_orders,
        actual_average_order_value=round(total_sales / total_orders, 2) if total_orders else None,
        total_guest_count=total_guests,
        actual_average_guest_spend=(
            round(total_sales / total_guests, 2) if total_guests else None
        ),
        warnings=warnings,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate normalized POS daily sales CSV.")
    parser.add_argument("csv_path")
    parser.add_argument("--show-records", action="store_true")
    args = parser.parse_args()
    try:
        records, summary = load_pos_daily_csv(args.csv_path)
    except PosDataValidationError as error:
        print(json.dumps({"valid": False, "errors": error.errors}, ensure_ascii=False, indent=2))
        return 1
    payload = {"valid": True, "summary": asdict(summary)}
    if args.show_records:
        payload["records"] = [asdict(record) for record in records]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
