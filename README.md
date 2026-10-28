# PenC Pocket

非官方的手機瀏覽器怪獸對打機模擬器試作。橫向／直向介面、ABC、
本機快照、聲音與手機晃動；所有遊戲內容從使用者選取的 BIN 讀取。
本專案不附 BIN、遊戲圖片、字型、音樂或韌體反組譯。

## 開啟與存檔

網站使用 HTTPS。按 Menu 選取支援的 8 MiB BIN，不需另外選 JSON。
目前識別 R18、R19、R20、R19h3、R20h4、原版超代彩 TEST4 與
DMC 線條小狗 v4.1 的固定內容雜湊；同名或其他版本不代表相容。
功能尚非完整實機模擬，機型間的音效、晃動、離開補算支援程度不同。

首次啟動從 jsDelivr 下載未修改的 Pyodide 0.27.7，需網路。
此版不是離線 PWA。瀏覽器可能要求第一次觸控後啟用聲音與動作權限。

BIN 與存檔存在這個網站自己的瀏覽器儲存區，不會自動從舊網址搬來。
換網址前在舊站 Menu 匯出快照，再於新站載入相同 BIN、匯入快照。
定期匯出：清除網站資料或系統回收儲存區可能移除本機進度。
R19h3/R20h4 公開設定已去除不用於執行的建置路徑；只對清冊列出的
舊、新設定雜湊執行資料不變的快照轉換，其他核心／BIN／RAM 檢查保留。

## QR 對戰與合體

**本次 GitHub Pages 部署預設不提供網路配對。** Pages 只能託管靜態
檔案，無法執行原有的配對伺服器及資料庫。單機功能可用；配對按鈕會
顯示尚未設定服務。原生連線模擬與 QR 客戶端原始碼仍隨本專案提供。

經營者可在 `public/hosting.js` 的 `configuredRelay` 設定相容的 HTTPS
API，再重建。這不是任意訊號伺服器 URL：需要實作 native-link 封包
協定、CORS、權杖驗證、封包順序、斷線、逾時、濫用限制；參閱
`docs/relay.md`。原本私人網站依賴平台驗證，不能直接當跨站服務。
兩個裝置須使用相同網站與 relay。不得把憑證或私人金鑰寫進前端。

## 本機修改與重建

需要 Python 3.12+；測試另需 Node.js 22+。建站本身不需 npm install。

```sh
node --test tests/*.test.mjs
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
本次核心只補來源註記，Python AST 與原版相同。若改核心行為，
需自行決定新的快照相容政策，不能沿用此保證。

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
