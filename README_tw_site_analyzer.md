# GDO店面選址分析器

這是一個可擴充的 Python 選址分析系統。使用者輸入台灣縣市、鄉鎮市區、路段或地標後，系統會輸出：

1. 中文可讀報告
2. 可給前端或 API 使用的結構化 JSON

## 核心能力

- 人潮分析：morning、noon、evening、midnight 四時段，分數 0-100。
- 車潮分析：car、motorcycle 分數 0-100。
- 餐飲競爭：附近 1km、2km、3km 店家數、類型分布、密度與競爭等級。
- 資料不足時會清楚標示「推估值」，並在 `warnings` 與 `assumptions` 說明推估邏輯。
- 開店找點報告：營收表現、月營收分布、客單價分布、前三名競品及好評/差評摘要。
- 市場證據快照：每次分析只解析一次地址並取得一次店家證據，區分已取得、零筆、部分取得與取得失敗。
- 可追溯契約：每份市場報告包含分析識別碼、分析版本、契約版本、來源與取得時間。

## 架構邊界

- `market_evidence.py`：集中外部市場證據、12 秒截止、競品分層與評論取得。
- `market_contract.py`：集中 `market-report-v2` JSON 契約與輸出驗證。
- `application.py`：集中端點驗證、分析執行與應用錯誤契約。
- `server.py`：只負責 HTTP 收送與靜態檔案。
- `observability.py`：提供部署版本、依賴 readiness、請求統計與最近一次市場報告狀態。

部署健康檢查：

```text
GET /api/health
```

健康回應不包含 API 金鑰、完整地址或可識別使用者的資訊。

## 快速使用

```powershell
python -m tw_site_analyzer.cli "高雄市 左營區 巨蛋商圈"
```

## 手機版查詢頁

啟動本機 Web 服務：

```powershell
python -m tw_site_analyzer.server --host 0.0.0.0 --port 8787
```

同一台電腦可開：

```text
http://127.0.0.1:8787
```

手機要連同一個 Wi-Fi，並用電腦的區網 IP 開啟：

```text
http://你的電腦IP:8787
```

若直接用檔案方式開啟 `web_mobile/index.html`，前端會自動呼叫：

```text
http://127.0.0.1:8787/api/analyze
```

所以仍需先啟動本機 Web 服務。

## 建議 API 架構

| 技能類型 | 用途 | 推薦工具/API |
| --- | --- | --- |
| 地理編碼 | 地址轉座標 | Google Geocoding API / TomTom |
| 車潮分析 | 汽車、機車流量 | TDX VD 即時車流 API |
| 人潮分析 | 早中晚半夜人潮強度 | 人口密度 + VD 車流 + 餐飲密度代理 |
| 餐飲競爭分析 | 附近餐飲店數與類型 | Google Places API / OpenStreetMap |
| 程式語言與架構 | 資料處理與 API 串接 | Python 3.11 + 模組化設計 |

只輸出 JSON：

```powershell
python -m tw_site_analyzer.cli "台北市 大安區 忠孝復興站" --json-only
```

輸出到檔案：

```powershell
python -m tw_site_analyzer.cli "台南市 中西區 國華街" --output-dir outputs/site_selection
```

## 可接入的資料來源

目前系統已預留以下接入點：

- 地理編碼：TGOS、Google Maps、Nominatim 或內部地標資料庫。
- 交通資料：TDX County/City Real-time Traffic Information VD。
- 餐飲資料：經濟部商業發展署商業登記餐飲業資料、Google Places、內部商圈資料。
- 人口/統計資料：統計區人口、行政區人口密度、門市內部交易資料。

第一版若未提供外部資料，會使用內建行政區座標與商業強度代理指標，並明確標示為推估。

## 環境變數

```powershell
$env:TW_RESTAURANT_CSV="C:\data\restaurants.csv"
$env:TW_TRAFFIC_VD_JSON="C:\data\tdx_vd_snapshot.json"
```

餐飲 CSV 建議欄位：

- `name`
- `address`
- `county`
- `district`
- `category`
- `status`
- `lat`
- `lon`

若沒有座標，系統會用縣市/行政區與地址關鍵字做粗略篩選，並加入警告。

交通 JSON 建議欄位：

- `lat`
- `lon`
- `car_flow`
- `motorcycle_flow`
- `speed`
- `timestamp`
- `source`

## 測試

```powershell
python -B -m unittest discover -s tests
```

## 反向選址推薦 API

```text
POST http://127.0.0.1:8787/api/recommend
```

範例 body：

```json
{
  "business_type": "炸雞",
  "county": "高雄市",
  "district": "三民區"
}
```

回傳內容包含推薦區域排序、業態適配分數、管理動作、中文報告與前端可用 JSON。若 `district` 留空，系統會比較該縣市內的候選行政區；若有指定行政區，系統會在該區內產生商圈、車站、夜市、市場、學區、主要道路等候選點。
