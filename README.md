# HYD2026_Taichung

臺中市水湳經貿園區周邊研究資料與地圖。

線上瀏覽（GitHub Pages）：https://yunching0513.github.io/HYD2026_Taichung/

## 成果

### Xitun & Beitun Base Map 西屯・北屯基本圖（`map/index.html`）

介面以英文為主、中文為輔：地圖標籤、圖例與側欄皆以英文呈現，里名、區名、分區與建設名稱附上中文；搜尋可輸入英文或中文里名。

- 西屯區、北屯區的區界與81個里界，疊在OpenStreetMap底圖上，區底色區分行政區
- 拖曳平移、滾輪或雙指縮放；方向鍵平移、`+`／`-`縮放、`0`回到全圖
- 滑過里顯示名稱與面積；點選或搜尋里名可查看面積、占行政區比例、面積排序與村里代碼
- 圖框邊緣標示經緯度刻度，附比例尺與指北針
- 側欄：水湳機場原址細部計畫土地使用面積（2024）與園區重大建設進度（2026）

成果首頁（`index.html`）列出地圖與可下載的原始資料。

## OpenStreetMap底圖

地圖採Web Mercator投影，直接載入OSM標準圖磚：

```
https://tile.openstreetmap.org/{z}/{x}/{y}.png
```

- 圖上與資料說明都標示了「© OpenStreetMap contributors」，這是[OSM圖磚使用政策](https://operations.osmfoundation.org/policies/tiles/)的要求，請勿移除。
- 政策允許一般瀏覽用量，但禁止大量下載或預先抓取圖磚。流量變大時，應改用商用圖磚服務或自架圖磚。
- 側欄的「OSM底圖」可以關閉底圖。圖磚載入失敗時，地圖會自動改為無底圖顯示。
- 以`file://`直接開啟時，瀏覽器不會送出Referer，OSM可能拒絕提供圖磚。在本機預覽請改用：

  ```sh
  python3 -m http.server 8000
  # 再開啟 http://localhost:8000/
  ```

- 要換成其他圖磚來源，修改`templates/basemap.html`裡的`TILE_URL`，並同步更新圖上的出處標示。

## 發布到GitHub Pages

網站是純靜態檔案，直接由分支根目錄發布（`.nojekyll`讓GitHub原樣提供檔案）：

1. 到repo的 **Settings → Pages**
2. **Build and deployment → Source** 選 **Deploy from a branch**
3. **Branch** 選`claude/gracious-ride-hxhf3w`（目前的預設分支），資料夾選`/ (root)`，按 **Save**
4. 約一分鐘後，網站會出現在 https://yunching0513.github.io/HYD2026_Taichung/

之後每次push到該分支，GitHub都會自動重新發布。若日後改用`main`作為主要分支，記得在同一頁把發布分支改成`main`。

## 重新建置

修改`data/raw/`中的資料或`templates/`中的模板後，執行：

```sh
python3 scripts/build_map.py
```

腳本只使用Python標準函式庫，會把GeoJSON與CSV內嵌進頁面，產生`index.html`與`map/index.html`。產生的檔案需要一併commit，GitHub Pages才會更新。

## 資料

| 檔案 | 內容 | 來源 |
|---|---|---|
| `data/raw/context_xitun_beitun_districts.geojson` | 西屯區、北屯區區界 | 內政部行政區界（2025-03-18）、國土測繪中心村里界（2026-08-17），經plotdb/pdmaptw v2.4.0處理；政府資料開放授權條款第1版 |
| `data/raw/context_xitun_beitun_villages.geojson` | 81個里界 | 同上 |
| `data/raw/shuinan_zoning_areas_2024.csv` | 水湳機場原址細部計畫各分區面積 | 臺中市政府都市發展局，第二次通盤檢討公開展覽說明會資料（2024-02-01） |
| `data/raw/shuinan_major_projects_2026.csv` | 園區重大建設進度 | 臺中市政府專案報告（2025-09-30、2026-08-03）及新聞報導，見各列`source`欄 |

注意事項：

- 邊界為簡化版本（81里合計約800個頂點），適合示意與脈絡判讀，不宜用於量測或精確套疊；面積數值取自資料屬性欄位。
- 重大建設表未附座標，因此尚未標示在地圖上。
- 座標系統為WGS84經緯度（CRS84）。

## 目錄

```
index.html              成果首頁（建置產生）
map/index.html          互動地圖（建置產生）
templates/              頁面模板
scripts/build_map.py    建置腳本
data/raw/               原始資料
```
