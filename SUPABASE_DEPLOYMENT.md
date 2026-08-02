# GDO Supabase 部署約定

GDO 選址系統使用獨立 Supabase 專案保存案件、候選地點、報告版本、勘查、留言與通知。

## Render 環境變數

- `SUPABASE_URL`: GDO 專用 Supabase 專案 URL。
- `SUPABASE_SECRET_KEY`: 僅限 Render 後端使用的 secret key。
- `GDO_AUTH_SECRET`: GDO 登入憑證簽章密鑰。
- `GDO_ADMIN_EMAIL`: 初始總部管理員 Email。
- `GDO_ADMIN_PASSWORD`: 初始總部管理員密碼。
- `GDO_ADMIN_NAME`: 初始總部管理員顯示名稱。

## 隔離原則

- 資料表一律使用 `gdo_` 前綴。
- 勘查照片只存入私有 `gdo-surveys` bucket。
- 瀏覽器不得取得 `SUPABASE_SECRET_KEY`。
- 不得共用其他公司或品牌的 Supabase 專案、金鑰或資料表。
- SQLite 僅作為本機開發備援；正式 Render 環境必須使用 Supabase。

## 驗收標準

1. `/api/health` 回報 `database_provider: supabase`。
2. 管理員可登入並建立案件。
3. 候選地點、報告版本與勘查照片可正常儲存。
4. Render 重新部署後，重新登入仍可讀取原有案件。
