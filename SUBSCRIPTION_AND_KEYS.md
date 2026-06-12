# 帳號、訂閱與金鑰清單

## 結論

要讓手機版選址分析器可以「任何地方都能用」且「準確度最高」，你需要處理三類外部資源：

1. 雲端部署平台：讓系統有公開 HTTPS 網址。
2. Google Maps Platform：提供高準確地址座標與店家 POI。
3. TDX：提供道路監測點與車流資料。

## 必辦

| 項目 | 是否要付費 | 你要做什麼 | 拿到什麼 |
| --- | --- | --- | --- |
| Render 或 Railway | 可先免費，正式建議付費 | 註冊帳號，連 GitHub | 公開網址 |
| Google Maps Platform | 需綁信用卡，可設預算上限 | 建立專案，啟用 Geocoding API、Places API | `GOOGLE_MAPS_API_KEY` |
| TDX 運輸資料流通服務 | 通常免費會員 | 註冊並建立應用 | `TDX_CLIENT_ID`、`TDX_CLIENT_SECRET` |

## 建議啟用的 Google API

| API | 用途 |
| --- | --- |
| Geocoding API | 中文地址、路段、地標轉座標 |
| Places API | 查 1km、2km、3km 內餐飲店家、類型、營業狀態 |
| Maps JavaScript API | 之後若要加地圖視覺化再開 |

## 建議設定的環境變數

```text
GOOGLE_MAPS_API_KEY=你的 Google Maps API Key
TDX_CLIENT_ID=你的 TDX Client ID
TDX_CLIENT_SECRET=你的 TDX Client Secret
TDX_VD_URL=你要查詢的 TDX VD API URL
HOST=0.0.0.0
PORT=8787
```

## 成本控管

| 項目 | 建議控管 |
| --- | --- |
| Google Maps | 設每日配額、月預算警示、限制 API Key 只能用指定網域 |
| Render/Railway | 先用免費或最低方案，正式使用再升級 |
| TDX | 先用會員 API，搭配快取避免頻繁請求 |

## 你拿到金鑰後交給我要填的資料

```text
GOOGLE_MAPS_API_KEY=
TDX_CLIENT_ID=
TDX_CLIENT_SECRET=
TDX_VD_URL=
```

`TDX_VD_URL` 可以先空白；我會依你要優先分析的縣市，幫你補最適合的 VD 端點。
