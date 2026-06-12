from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analysis import SiteSelectionAnalyzer, public_json
from .report import build_chinese_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Taiwan storefront site selection analyzer")
    parser.add_argument("location", help="中文縣市、鄉鎮區、路段或地標")
    parser.add_argument("--json-only", action="store_true", help="只輸出 JSON")
    parser.add_argument("--output-dir", help="將 report.md 與 response.json 輸出到指定資料夾")
    args = parser.parse_args(argv)

    analyzer = SiteSelectionAnalyzer()
    result = public_json(analyzer.analyze(args.location))
    report = build_chinese_report(result)
    json_text = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(ch for ch in args.location if ch.isalnum() or ch in ("_", "-"))[:40] or "site"
        (output_dir / f"{safe_name}_report.md").write_text(report, encoding="utf-8")
        (output_dir / f"{safe_name}_response.json").write_text(json_text, encoding="utf-8")

    if args.json_only:
        print(json_text)
    else:
        print(report)
        print("\n--- JSON ---")
        print(json_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
