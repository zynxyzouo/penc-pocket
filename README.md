# PenC Pocket

非官方的手機瀏覽器怪獸對打機模擬器試作。橫向／直向介面、ABC、
本機快照、聲音與手機晃動；所有遊戲內容從使用者選取的 BIN 讀取。
本專案不附 BIN、遊戲圖片、字型、音樂或韌體反組譯。

## 開啟與存檔

網站使用 HTTPS。按 Menu 選取支援的 8 MiB BIN，不需另外選 JSON。
預設記住這台裝置選過的 BIN；下次進入首頁會自動載入最後使用的 BIN
與其存檔，點畫面「繼續」開始遊戲、啟用聲音與晃動。首次使用、取消
記住 BIN 或瀏覽器資料已清除時，仍需自行選檔；網站不提供 BIN 下載。
目前內建 R23 EXPERIMENTAL、原版超代彩 TEST4 與
DMC 線條小狗 v4.1 的固定內容雜湊；同名或其他版本不代表相容。
功能尚非完整實機模擬，機型間的音效、晃動、離開補算支援程度不同。

首次啟動從 jsDelivr 下載未修改的 Pyodide 0.27.7，需網路。
此版不是離線 PWA。瀏覽器可能要求第一次觸控後啟用聲音與動作權限。

PenC 核心使用指令快取減少重複解碼；裝置效能仍會影響動畫與按鍵速度。
離開補算期間約每 250 ms 更新畫面，完成或暫停時顯示最新狀態。
補算仍逐秒交給原生流程處理，保留飢餓、睡眠與進化等事件；離開越久，
可能仍需等待。點畫面可暫停補算，尚未結算的時間會保留。

BIN 與存檔存在這個網站自己的瀏覽器儲存區，不會自動從舊網址搬來。
換網址前在舊站 Menu 匯出快照，再於新站載入相同 BIN、匯入快照。
定期匯出：清除網站資料或系統回收儲存區可能移除本機進度。
舊版 PenC 設定已從網站發布包移除；不刪除瀏覽器中既有的 BIN 或存檔。
舊版儲存設定與已知設定雜湊的相容處理保留。不同 BIN 的快照不能直接
當成 R23 存檔；新載入 R23 從原生開機、設定時間與選蛋開始。

## QR 對戰與合體

這版使用 **Cloudflare Workers Free + SQLite Durable Objects** 轉送
遊戲原生封包，不使用付費 TURN。兩人開啟同一網站的連線選單，任一方
掃描對方 QR；配對完成後回到 BIN 內 BATTLE／JOGRES，依遊戲流程操作。
連線狀態可點擊中斷；關閉頁面或額滿會結束連線。
不同 BIN 只要原生通訊相容就能配對。伺服器不替遊戲計算對戰或合體。
機型能開機不代表原生連線已支援；TEST4／DMC 尚未完成連線驗證。

部署與免費方案限制見 [docs/cloudflare-setup.md](docs/cloudflare-setup.md)，
協定見 [docs/cloudflare-contract.md](docs/cloudflare-contract.md)。
2026-10-28 正式服務通過封包、瀏覽器跨站連線、原生混版對戰及合體
測試；兩支實體 iPhone 互連仍待實測。預設每日 8,000 次 API 請求，測試者
共用；350 ms 輪詢下最多約 23 分鐘雙人連線時間，滿額停止。
台灣時間每天 08:00 重置。此程式不會自動升級付費；帳號須維持 Workers
Free。單機養成不使用連線額度。經營者可在 `public/hosting.js` 更換已驗證
的相容 HTTPS API 再重建，或設為 `null` 關閉網路配對。

## 本機修改與重建

需要 Python 3.12+；測試另需 Node.js 22+。建站本身不需 npm install。

```sh
node --test tests/*.test.mjs
python -B -m unittest discover -s tests -p 'test_*.py'
python tools/build.py
python -m http.server 8766 --directory dist
```

開啟 `http://localhost:8766/`。`dist/` 是可部署的網站；Menu 的原始碼
下載是同次建置的 `downloads/penc-pocket-source.zip`，包含可修改的
HTML/JS/Python、授權、測試、腳本和 QR 函式庫的偏好修改形式。
每次建置重新產生核心／設定檔的完整性雜湊和發布清單。

`release-files.json` 是明確允許的來源檔清單。新增來源檔時手動加入，
不要用整個研究資料夾或既有 Git 歷史替代此發布集合。
`third_party/jsqr-1.4.0/` 有固定上游 TypeScript 與原始建置設定；
修改 QR 函式庫時按 `third_party/README.md` 重建，再執行
`python tools/prepare_vendor.py` 更新瀏覽器包裝。

三個 `core_sha256` 值保留舊版快照 ABI 識別，並非本次所有檔案的
合併雜湊；實際下載驗證用 `core-config.json` 的逐檔雜湊。
R23 更新只擴充已核對原生區段的精確 BIN 白名單，沒有改動快照格式
或 CPU 指令。後續核心行為修改仍須另行決定快照相容政策。

選用實際 R23 的整合測試：將環境變數 `PENC_R23_BIN` 設為本機 BIN
路徑再執行 Python 測試。未提供 BIN 時，CI 明確跳過該測試；公開
套件不含測試用韌體。測試包含原生開機、時間、選蛋、孵化、音量、
亮度、快照往返與短時間離開補算，不代表完整生命週期或實機等效。

## GitHub Pages

把本來源樹放進**新建的公開 repository**，預設分支設為 `main`。
Settings → Pages → Build and deployment 選 GitHub Actions。
隨附 `.github/workflows/pages.yml` 會測試、建置、部署 `dist/`。
支援 `https://帳號.github.io/專案名稱/` 的子路徑。
網站更新必須連同原始碼下載一起更新，不要只複製壓縮產物。

## 授權與來源

本發布集合中自行撰寫及改編的模擬器、介面、設定、建置腳本與文件，
除另有註記者外，以 **GNU GPL version 3 or (at your option) any later
version — GPL-3.0-or-later** 提供。見完整 `LICENSE`。
你可以依該授權使用、修改、再散布及商用；軟體按現狀提供，沒有擔保。

CPU 相關實作改編自 MAME 0.289 unSP（上游 GPL-2.0-or-later），
上游著作權人為 Segher Boessenkool、Ryan Holtz、David Haywood。
保留 `Copyright 2008-2017 Segher Boessenkool` 原告知。
來源：https://github.com/mamedev/mame/tree/mame0289/src/devices/cpu/unsp

QR 函式庫各自保留 MIT／Apache-2.0；外部 Pyodide 和其執行環境各自
適用原授權，GPL 宣告不取代那些條款。完整清冊與來源見
`public/licenses/THIRD-PARTY-NOTICES.txt`、`third_party/README.md`。
修改摘要和日期見 `MODIFICATIONS.md`。

BIN、遊戲圖片、音樂及商標權不由這份軟體授權授予。本專案與
Bandai、Digimon、MAME 官方無隸屬或背書關係。
