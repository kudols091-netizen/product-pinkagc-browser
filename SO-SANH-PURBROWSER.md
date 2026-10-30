# PURBrowser — Reverse-Engineer đầy đủ (A-Z) & Gap Analysis cho PinkAgc Browser

> Quét bằng **leanrea** + decompile .NET (30/10/2026). Nguồn: `D:\PURBrowser` (bản cài sạch).
> Decompile: tách single-file bundle bằng `sfextract` → `PURBrowser.dll` (10.17MB) → `ilspycmd` ra 425 file C#.
> Ký hiệu: **[SEEN]** = thấy trực tiếp trong code/DB/settings · **[INFER]** = suy ra.

---

## 1. Kiến trúc [SEEN]
| Lớp | PURBrowser | PinkAgc Browser |
|---|---|---|
| App quản lý | `PURBrowser.exe` 164MB = **.NET 8 WPF**, self-contained single-file | Python + SPA 1 file |
| Automation lib | **PuppeteerSharp** + **WebDriverBiDi** (CDP/BiDi) | CDP tự viết |
| Engine | Chromium **156** (+ fpchromium), **tải theo yêu cầu** (`EngineInstallService`, nhiều version song song) | ovobrowser 150 bundle cứng |
| DB | SQLite `purbrowser.db` (bảng Data=JSON) | SQLite GPM-compatible |
| Crypto | BouncyCastle + `PurCrypto` (mã hoá field nhạy cảm, `enc:salt`) | — |
| License | HWID (`HwidGenerator`, `PurLicenseStore`, `LicenseGate`) | HMAC+RSA HWID (giống) |

→ **Cùng mô hình với PinkAgc**, nhưng PURBrowser nhắm thẳng thị trường **MMO/nuôi nick Facebook VN**.

---

## 2. ⭐ AUTOMATION — danh mục đầy đủ (~98 block, 5 nhóm) [SEEN: `BlockCatalog.cs`]
Đây là chỗ PinkAgc yếu nhất (builder v1 ~12 action). PURBrowser có **~98 block**:

**General (8):** Start, End, Delay, RandomDelay, Log, Clipboard, **Command (shell)**, **PowerShell**

**Browser (54):** Navigate, NewTab, SwitchTab, CloseTab, CloseBrowser, Reload, GoBack, GoForward, Click, Hover, InputText, **HumanType** (gõ như người), ClearField, Select, Check, PressKey, UploadFile, Scroll, ScrollTo, Wait, GetText, GetAttribute, Screenshot, ExecuteJs, RandomScroll, DoubleClick, RightClick, **MouseMove (human)**, DragDrop, WaitText, WaitUrl, GetUrl, GetTitle, ElementExists, CountElements, ScreenshotElement, HandleDialog (auto dialog), CloseOtherTabs, FocusTab, GetCookies, SetCookie, ClearCookies, **RotateProxy**, Comment, **CheckProxy** (auto-đổi từ list + ép country), HasPopup, WaitPopup, ActiveTab, WaitUrlChanged, ImportCookie, ExportCookie, MousePress, MouseRelease, TryClick

**Data (26):** FileExists, DeleteFile, CopyFile, MoveFile, ReadLines, FolderExists, CreateFolder, DeleteFolder, FolderList, HttpDownload, SplitText, RandomNumber, MathExec, IncVar, InsertData (SetVariable), ReadData, **RandomData** (name/email/username/password/uuid/phone), RandomDate, **HttpRequest**, **BrowserRequest** (fetch trong context browser), **ExtractRegex**, **ParseJson**, ReadFile, WriteFile, RandomLine, **PopAccount** (hàng đợi account từ file)

**Logic (7):** ForEach, Loop, WhileExists, IfVar (==/!=/>/</contains/empty), Stop, Throw, Condition (gate theo phần tử)

**Account (3):** **Generate2FA** (TOTP), **SolveCaptcha** (omocaptcha/2captcha/anticaptcha/capmonster · recaptcha v2/v3/hcaptcha/image · auto-inject), **Telegram** (notify)

**Điểm tinh vi [SEEN]:** mỗi action có `retry` + `timeout` + `scope` (tìm trong khung) + `expect` (chờ sau thao tác) + `selector2/selector3` (selector dự phòng); hành vi **giống người** (HumanType/MouseMove/RandomScroll); hỗ trợ CSS **và** XPath; biến `{{var}}` khắp nơi.

**Hạ tầng automation khác [SEEN]:** `AutomationRunner.cs` (102KB — engine), `RpaRecorder.cs` (ghi thao tác → workflow), `SchedulerService.cs` (hẹn giờ), `WorkflowVersionService` (version script), `RunHistoryService` (lịch sử chạy). Workflow là **đồ thị node** (WorkflowNode/Connection, cổng xanh/đỏ), không phải list tuần tự.

---

## 3. 🤖 AI SUBSYSTEM — rất mạnh [SEEN: `Services.Ai\` 80+ file]
Thứ PURBrowser hơn hẳn mọi đối thủ (kể cả GPM):
- **SmartRecorder / RecordingWorkflowBuilder**: ghi lại thao tác người dùng → tự sinh workflow.
- **AiWorkflowBuilder / AiAgent**: gõ yêu cầu bằng lời → AI dựng workflow (AddNode/Connect/Patch).
- **AiPageExplorer / PageInspector / PageSnapshot / PageGrounding**: AI "nhìn" trang (DOM + screenshot) → chọn đúng selector, có **grounding** (chống bịa selector).
- **AiWorkflowDoctor / WorkflowLinter / WorkflowQuality**: AI tự kiểm & sửa workflow hỏng.
- **GeminiProvider** + `AiModelRegistry` (đa model), `SecretSanitizer` (giấu secret khỏi prompt), local model.

---

## 4. Local API + tương thích GPM [SEEN: `LocalApiServer.cs` 41KB, `GpmApi.cs` 16KB]
- API local `http://127.0.0.1:50325`, routes `/api/v1/...` + `/status`, có token.
- **Tương thích GPM API** → script/tool viết sẵn cho GPM dùng được với PURBrowser (mở profile → trả CDP endpoint + debugPort). Mỗi Profile có `RemoteDebugPort`.
- Ship sẵn `chromedriver.exe` → Selenium chạy ngay.

---

## 5. Earn + Facebook module (đặc thị trường VN) [SEEN]
- **Earn**: `EarnAccount` (email/pass/2FA/token/cookie/recovery/health/state) + `EarnJobRunner` + tích hợp **`public.traodoituongtac.com`** (nền tảng trao đổi tương tác VN — kiếm điểm bằng like/follow). Bảng Earn* trong DB.
- **Facebook**: `FacebookActions.cs` (40KB), `EarnFacebookLogin`, `FacebookInfo`, `FbReaction` — login FB, thả cảm xúc, lấy info. Nhắm thẳng dân nuôi nick FB.

---

## 6. Fingerprint model [SEEN: `Profile.cs`] — ngang PinkAgc
FingerprintSeed+Salt (per-profile), GPU pool (WebGlVendor/Renderer/GpuProfile), Canvas/WebGL/Audio/MediaDevices/ClientRects = **Noise**, HardwareConcurrency, DeviceMemory, WebRtcMode(Disabled)+FixedIp, Timezone(auto theo proxy), Geo(theo proxy)+permission, ScreenResolution, Language, DoNotTrack, UA custom, OsType.
**PURBrowser thêm:** `BandwidthMode`/`DisableImages`/`DirectStaticExt` (**tiết kiệm băng thông** — chặn ảnh để farm số lượng lớn), `EngineVersion` per-profile.

---

## 7. 🔴 GAP — PinkAgc NÊN BỔ SUNG (ưu tiên)

| # | Hạng mục | PURBrowser | PinkAgc | Đề xuất |
|---|---|---|---|---|
| 1 | **Automation platform** | ~98 block + retry/scope/expect/human + đồ thị node + version + lịch sử | builder v1 ~12 action | **Ưu tiên 1.** Bổ sung block theo nhóm (Browser/Data/Logic/Account), retry/timeout/selector dự phòng, biến `{{var}}`, loop/condition, HumanType/human-mouse. |
| 2 | **Local API tương thích GPM** + ship chromedriver | `/api/v1` port 50325, GPM-compat, token | có `/api/v3` | Làm API trả CDP endpoint + **tương thích GPM** → ăn được hệ sinh thái script GPM/AdsPower. |
| 3 | **AI automation** | SmartRecorder + AI dựng/sửa workflow + AI nhìn trang | có MCP (nền tốt) | Tận dụng MCP sẵn: AI step + recorder thao tác → workflow + AI chọn selector. Khác biệt hoá mạnh. |
| 4 | **Captcha + 2FA + Telegram** trong automation | omocaptcha/2captcha/anticaptcha/capmonster, TOTP, Telegram | — | Block SolveCaptcha + Generate2FA + Telegram notify. |
| 5 | **Scheduler + Run history + Script version** | đủ | chạy tay | Hẹn giờ cron + log chạy + version script. |
| 6 | **Tiết kiệm băng thông** (chặn ảnh/static) | có | [?] | Chế độ block images/CSS → farm nhiều nick tốn ít proxy. |
| 7 | **Earn/Facebook module** | account farm + traodoituongtac + FB actions | — | Chỉ làm nếu nhắm dân MMO/nuôi nick VN (PinkAgc Manager vốn là tool FB → **rất hợp tệp khách**). |
| 8 | **Engine tải theo yêu cầu** (nhiều version) | có | bundle cứng 150 | Cho tải/chọn nhiều version Chromium per-profile. |
| 9 | Window tiling, cookie import/export block, mã hoá DB at-rest, RPA recorder | có | một phần | Bổ sung dần (UX + bảo mật). |

## 8. 🟢 PinkAgc ĐANG HƠN / NGANG
- **Cloud/Team sync** (`team.pinkagc.com`): PURBrowser **chỉ sync/backup local** [SEEN: không có cloud/team server]. → **Lợi thế rõ của PinkAgc.**
- **Open-core / self-host**, **MCP** (nền AI sẵn), antidetect đã verify ip8 100% (hơn GPM).
- Fingerprint surface **ngang** PURBrowser.

## 9. Lộ trình đề xuất (lazy, đúng trọng tâm)
1. **Automation platform** (gap #1) — mở rộng builder lên ~40-50 block cốt lõi trước (Browser + Logic + Data + retry/selector). Đây là khoảng cách lớn nhất.
2. **Local API + GPM-compat + chromedriver** (#2) — ăn hệ sinh thái automation sẵn có.
3. **Captcha/2FA/Telegram block** (#4) + **Scheduler/Run history** (#5) — hoàn thiện automation.
4. **AI step + recorder** (#3) — tận dụng MCP, khác biệt hoá.
5. Earn/FB module (#7) — chỉ nếu chốt tệp khách MMO VN (hợp với PinkAgc Manager).

> **Đã decompile sâu**: automation block catalog + param = [SEEN] đầy đủ. Engine runtime `AutomationRunner.cs` (102KB) chưa đọc chi tiết từng hàm (không cần cho gap). Code nguồn tạm ở scratchpad `pur_src/` (425 file) nếu cần tra thêm.
