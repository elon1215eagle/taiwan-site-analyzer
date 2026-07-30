# GDO店面選址分析器

這是吉多國際餐飲／LAIGDO 的加盟展店選址與案件管理系統。所有功能均須登入，正式支援炸雞、火鍋、燒烤及便當。

1. 中文可讀報告
2. 可給前端或 API 使用的結構化 JSON

## 核心能力

- 雙核心模式：指定地址分析、反查推薦區域。
- 固定分析半徑：炸雞／便當 1 公里，火鍋／燒烤 2 公里。
- 五大構面：商圈需求、同業競爭、交通可達性、消費與價格帶、營收潛力。
- 獨立資料信心度及三種選址篩選結論。
- 地址報告：圈層比較、真實地圖、主要同類競品、評論、市場客單價帶及營收情境推估。
- 反查推薦：戶政人口資料排名前三行政區，再從真實店家地址聚合前五道路熱點。
- 案件管理：三角色權限、現勘、三店比較、送審及站內通知。
- 市場證據快照：每次分析只解析一次地址並取得一次店家證據，區分已取得、零筆、部分取得與取得失敗。
- 可追溯契約：每份市場報告包含分析識別碼、分析版本、契約版本、來源與取得時間。

## 架構邊界

- `market_evidence.py`：集中外部市場證據、12 秒截止、競品分層與評論取得。
- `decision.py`：集中四業態半徑、五構面、信心度、結論及營收情境規則。
- `market_contract.py`：集中 `market-report-v4` JSON 契約與輸出驗證。
- `workspace.py`：集中登入、角色、案件、候選店面、現勘、送審與通知。
- `population.py`：取得戶政司免費行政區人口證據。
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

## 響應式營運工作台

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

前端必須由 Web 服務開啟，不支援直接開啟本機 HTML 檔案。

## 建議 API 架構

| 技能類型 | 用途 | 推薦工具/API |
| --- | --- | --- |
| 地理編碼 | 地址轉座標 | Google Geocoding API / TomTom |
| 車潮分析 | 汽車、機車流量 | TDX VD 即時車流 API |
| 商圈活動 | 人口、商業、道路車流等代理證據 | 戶政司 + TDX + Places |
| 現場行人流量 | 現勘單次計數 | 使用者現勘輸入 |
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
- 人口/統計資料：內政部戶政司行政區人口資料。

第一版若未提供外部資料，會使用內建行政區座標與商業強度代理指標，並明確標示為推估。

## 環境變數

```powershell
$env:TW_RESTAURANT_CSV="C:\data\restaurants.csv"
$env:TW_TRAFFIC_VD_JSON="C:\data\tdx_vd_snapshot.json"
$env:GDO_AUTH_SECRET="至少 24 字元的隨機密鑰"
$env:GDO_ADMIN_EMAIL="admin@example.com"
$env:GDO_ADMIN_PASSWORD="至少 10 字元的管理員密碼"
$env:GDO_DB_PATH="C:\data\gdo.sqlite3"
$env:GDO_DATABASE_PERSISTENT="true"
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

若 `district` 留空，系統以戶政人口證據及市場模型回傳前三行政區；若有指定行政區，系統只從實際店家地址聚合前五個可定位道路熱點。資料不足時不產生空泛商圈名稱。
