# POS／門市日營運資料接入規格

## 目的

將 LAIGDO 自有門市的 POS 匯出檔、關帳表或每日營運報表轉為 GDO 可驗證的日資料，用於真實營收、實際訂單客單價及相似門市基準。不得混入其他公司或品牌資料。

## 必要欄位

| 欄位 | 說明 |
|---|---|
| `store_id` | LAIGDO 內部門市代碼 |
| `store_name` | 門市名稱 |
| `business_date` | 營業日，格式 `YYYY-MM-DD` |
| `business_type` | 業態，例如炸雞 |
| `net_sales` | 扣除折扣與退款後的營業淨額 |
| `completed_orders` | 已完成且未作廢的訂單數 |

可選欄位：`guest_count`、`discount_amount`、`refund_amount`、`dine_in_sales`、`takeout_sales`、`delivery_sales`。

## 驗證方式

```powershell
python -m tw_site_analyzer.pos_data C:\path\to\normalized_pos_daily_sales.csv
```

正式資料可使用英文欄名，也支援「門市代碼、門市名稱、營業日、業態、營業淨額、完成訂單數」等中文欄名，不限定 POS 品牌。

## 資料治理

- 不匯入姓名、電話、會員編號、地址或付款識別資訊。
- 同一門市、同一營業日只允許一筆彙總資料。
- `實際訂單客單價 = 營業淨額 ÷ 完成訂單數`。
- `實際每人客單價 = 營業淨額 ÷ 來客數`，缺少完整來客數時不得產生。
- 原始檔應限制管理者存取；GDO 查詢只使用門市日彙總與匿名基準。
