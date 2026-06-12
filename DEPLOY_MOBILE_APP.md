# 手機版公開部署說明

## 結論

要做到「任何地方都能用手機查詢」，必須把目前本機服務部署到雲端，取得一個 HTTPS 網址。部署後手機可直接開網址，也可加入主畫面，像 App 一樣使用。

## 最快部署方式：Render

1. 把本資料夾推到 GitHub repository。
2. 登入 Render。
3. New + 選擇 Blueprint。
4. 選擇這個 repository。
5. Render 會讀取 `render.yaml` 並建立 Web Service。
6. 部署完成後會得到類似：

```text
https://taiwan-site-analyzer.onrender.com
```

手機開這個網址後，使用瀏覽器的「加入主畫面」即可安裝。

## Docker 部署

```powershell
docker build -t taiwan-site-analyzer .
docker run -p 8787:8787 taiwan-site-analyzer
```

## 環境變數

| 變數 | 用途 |
| --- | --- |
| `HOST` | 雲端部署請設 `0.0.0.0` |
| `PORT` | 平台指定的連接埠 |
| `GOOGLE_MAPS_API_KEY` | Google Geocoding 與 Places API |
| `TDX_CLIENT_ID` | TDX API client id |
| `TDX_CLIENT_SECRET` | TDX API client secret |
| `TDX_VD_URL` | TDX VD API endpoint |
| `TW_RESTAURANT_CSV` | 餐飲資料 CSV 路徑 |
| `TW_TRAFFIC_VD_JSON` | TDX VD 快照 JSON 路徑 |

## 正式上線後建議

1. 綁定自己的網域，例如 `site.yourcompany.com`。
2. 接 Google Geocoding API，提高地址座標準確度。
3. 接 Google Places 或 OSM，提高餐飲競爭分析完整度。
4. 接 TDX VD API，把車潮由推估改為實測。
5. 加資料庫與排程更新，避免每次查詢都打外部 API。
