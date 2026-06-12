from __future__ import annotations


def build_chinese_report(result: dict) -> str:
    geo = result["geo_scope"]
    restaurant = result["restaurant_analysis"]
    traffic = result["traffic_analysis"]
    crowd = result["crowd_analysis"]
    data_quality = result.get("data_quality", {})
    lines = [
        f"# GDO店面選址分析報告",
        "",
        f"## 一、分析地點",
        f"- 輸入地點：{result['input_location']}",
        f"- 判讀範圍：{geo.get('county', '')}{geo.get('district', '')} {geo.get('address_or_landmark', '')}".strip(),
        "",
        "## 二、總結",
        f"- 綜合分數：{result['overall_score']}/100",
        f"- 結論：{result['overall_conclusion']}",
        "",
        "## 三、人潮分析（推估）",
    ]
    period_names = {"morning": "早上", "noon": "中午", "evening": "晚上", "midnight": "半夜"}
    for key, name in period_names.items():
        item = crowd[key]
        lines.append(f"- {name}：{item['score']}/100（{item['level']}）｜{item['reason']}")
    lines.extend(
        [
            "",
            "## 四、車潮分析",
            f"- 汽車：{traffic['car']['score']}/100（{traffic['car']['level']}）｜{traffic['car']['reason']}",
            f"- 機車：{traffic['motorcycle']['score']}/100（{traffic['motorcycle']['level']}）｜{traffic['motorcycle']['reason']}",
            "",
            "## 五、餐飲競爭分析",
            f"- 3km 內附近餐飲店數：{restaurant['nearby_count']}",
            f"- 餐飲密度：{restaurant['density_level']}",
            f"- 競爭程度：{restaurant['competition_level']}",
            f"- 半徑分布：{restaurant.get('counts_by_radius', {})}",
            f"- 判斷原因：{restaurant['reason']}",
            "- 類型分布："
        ]
    )
    for item in restaurant["category_summary"]:
        lines.append(f"  - {item['category']}：{item['count']}")
    if data_quality:
        lines.extend(
            [
                "",
                "## 六、資料精準度",
                f"- 可信度分數：{data_quality.get('score', 0)}/100",
                f"- 可信度等級：{data_quality.get('level', '')}",
            ]
        )
        for signal in data_quality.get("signals", []):
            lines.append(f"- {signal}")
    if result["warnings"]:
        lines.extend(["", "## 七、資料限制與警告"])
        for warning in result["warnings"]:
            lines.append(f"- {warning}")
    if result["assumptions"]:
        lines.extend(["", "## 八、推估假設"])
        for assumption in result["assumptions"]:
            lines.append(f"- {assumption}")
    return "\n".join(lines)
