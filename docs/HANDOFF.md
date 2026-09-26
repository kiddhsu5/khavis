# K.H.A.V.I.S. 交接文件

> 給接手的工程師或 AI agent。目標是「讀完就能動手」，不必回頭翻對話紀錄。
>
> **配套文件**：`HANDOFF.local.md`（repo 根目錄，**已 gitignore**）—— 部署主機、憑證位置、Tailscale 拓撲、Cloudflare、操作指令。裡面有基礎設施細節，**絕對不要 commit 進這個公開 repo**。
>
> 更新日期：2026-09-24

---

## 0. 怎麼用這份交接

1. 先讀 §1–2 掌握現況，讀 §3 知道從哪裡下鑽。
3. **動手前必讀 §6「已知陷阱」** —— 那些是踩過的坑，比文件更省時間。
4. 工作時守 §9 的 repo 慣例，尤其是 commit 格式與安全紅線。
5. 部署操作看 `HANDOFF.local.md`。

---

## 1. 專案一句話

**K.H.A.V.I.S. 是「個人 / homelab 開發者的 BYOK 純粹主義 LLM 路由器」** —— 把 12 個 LLM pool 聚合成單一介面，做智慧路由、額度容錯、多 agent 協作。永遠 Apache 2.0、零 markup、self-host。

這個定位是護城河，不是行銷詞。`docs/STRATEGY.md` §7.2 明文寫著：**不要加付費 tier、不要做企業 sales、不要做 SaaS**。任何往這三件事靠的提案都要先回頭讀那一節。

---

## 2. 現況快照（2026-09-24）

### 2.1 已完成並上線

| 區塊 | 狀態 |
| --- | --- |
| 核心路由器 `core/`（registry、capability 路由、audit log、YAML hot reload） | ✅ v0.1.0 已完成 |
| 12 個 pool 的 `ProviderPlugin`（`providers/`） | ✅ 完成 |
| Telegram 派工 bot `bot/`（三方 fan-out：claude / codex / K.H.A.V.I.S.） | ✅ 上線，polling 模式 |
| 多 agent 流水線 `agents/`（planner→coder→debate→critic→verify→learn） | ✅ 完成 |
| 公開狀態頁 `scripts/status_server.py` | ✅ 上線 `khavis.kiddhsu.taipei` |
| Web dashboard `/dashboard` `/wall` `/api/dashboard` | ✅ 2026-09-26 |
| bot Phase 4 `/phase` + `/history` | ✅ 2026-09-26 |
| security@ Email Routing + GPG `pgp.txt` | ✅ 2026-09-26 |
| Ollama 走 Tailscale（Mac / Surface 兩個 pool） | ✅ Mac 綠燈；Surface 待機器端處理 |
| 測試 | ✅ 290 tests green、0 ruff、0 mypy |

### 2.2 剛修完（詳見 §6.5 事件簿）

狀態頁的四個效能／穩定性 bug 全數修復並部署：

| commit | 問題 | 結果 |
| --- | --- | --- |
| `4ded48d` | 冷啟動時 `pool_health()` 同步跑完 12 pool 的 20s 掃描才回應 | 超過 Cloudflare ~15s origin 逾時 → 522 |
| `5f0e79d` | `_placeholder_rows()` 仍呼叫 `_load_plugins()`，把 provider SDK import（實測 2451ms）放回請求路徑 | 第二次回歸 |
| `9377dfd` | 我把 TLS 交握放在 `get_request()`，而它跑在 `serve_forever` 的 accept 執行緒上 | 交握阻塞 accept → Cloudflare 525 |
| `fb70fae` | `http.server.HTTPServer.server_bind` 最後一行 `socket.getfqdn(host)` 對無 PTR 的位址做反解 | **10.014 秒死窗** |

現在：啟動到可服務 0.28 秒，兩行 `listening on` 間隔 5ms（原本 10,014ms），穩態請求 1.3–5ms。

### 2.3 尚未開始 / 未追蹤

codex 寫了一批檔案**尚未 commit**，要不要收是使用者的決定（見 §8）：

- `docs/STRATEGY.md`、`docs/BENCHMARKS.md`、`docs/EDGE_FAILOVER.md`、`docs/FEATURE_MATRIX.md`
- `scripts/run_benchmarks.py`、`tests/benchmarks/`
- 已修改未 commit：`.github/workflows/test.yml`、`README.md`、`README.zh-TW.md`

收之前建議先修的瑕疵（都已定位）：

1. 「2× budget」的說法與測試裡的 1× assert、`run_benchmarks.py` 的 3× 三者不一致
2. `test_roundtrip_failover` 與 `TestHotReloadBenchmark` 都沒測它名字說的事
3. `pytest-bbenchmark` 拼字錯
4. 「具體型號見 commit history」這種句子應刪除
5. 約 100 行重複程式碼
6. `jobs.benchmarks.name` 用了 `${{ env.PYTHON_VERSION }}` —— `env` context 在 job-name 層級取不到

---

## 3. 程式碼導覽

```
core/          路由器本體。registry.py 的 PluginRegistry 自動發現 providers/ 並
               套用 config/pools.yaml。capability 路由在這裡。
providers/     每個供應商一個 plugin，繼承 base.ProviderPlugin。
               chat() / health_check() / list_models() / check_quota() 是介面。
agents/        多 agent 流水線。LangGraph，state.py 的每個可變 key 都必須有
               Annotated[Type, reducer]。
bot/           Telegram bot。dispatch.py 做三方 fan-out，backends/ 各一個後端，
               judge.py 用本地 Ollama 挑最佳答案。
scripts/       status_server.py（公開狀態頁）、launch_bot_daemon.py、
               integration_test.py、setup_ollama.sh
config/        pools.yaml（12 pool 設定）、capabilities.yaml、agents.yaml
deploy/        systemd unit、Dockerfile、Caddyfile
tests/         單元測試。跑法見 §4
docs/          架構、設定、營運、FAQ、策略
```

**加一個新 provider 只需**：在 `providers/` 放一個繼承 `ProviderPlugin` 的類別，registry 會自動發現。`docs/PLUGIN_DEVELOPMENT.md` 是規格。

**設定優先序**：`config/pools.yaml` 是唯一真相來源。`${MAC_IP}` / `${SURFACE_IP}` 這類 placeholder 由 `.env` 解析（`providers/ollama.py::_expand_env`），解析不到會變成 `<var>.local`，讓錯誤設定在健康頁上一目了然。

---

## 4. 測試與品質門檻

```bash
# 必須用 python3.12，不要用 python3（Mac 上是 3.9.6，pydantic 會在 import 炸掉）
python3.12 -m pytest --no-header
python3.12 -m ruff check .
python3.12 -m mypy core providers agents bot
```

- 目前 **290 tests green**、0 ruff、0 mypy
- `pyproject.toml` 設定 `>=3.11`
- mypy 的 `disable_error_code = ["misc", "unused-ignore", "assignment", "valid-type"]` 是刻意的，不要隨手移除
- `python3.12 -m pytest` 偶爾會噴 `libc++abi: recursive_mutex lock failed` 崩潰 —— 這是 `google.generativeai` → `grpc` 的原生碼問題，**與程式碼無關**（git stash 掉改動一樣會發生）。重跑即可。

---

## 5. 總體規劃

### 5.1 Roadmap（`README.md`）

| 版本 | 內容 | 狀態 |
| --- | --- | --- |
| v0.1.0 | 核心路由器、registry、12 pools、capability routing、audit log | ✅ |
| v0.2.0 | Token-aware 成本預算（per request / per session） | ⬜ 下一個 |
| v0.3.0 | 內建 RAG connector（Chroma、Qdrant、pgvector） | ⬜ |
| v0.4.0 | OpenAI 相容 drop-in server mode | ⬜ |
| v0.5.0 | 微調模型 registry + hot-swap | ⬜ |
| v0.6.0 | Web UI（pool 健康、額度儀表板） | ⬜ |
| v1.0.0 | 穩定 plugin API、SemVer 保證、LTS branch | ⬜ |

### 5.2 策略共識（`docs/STRATEGY.md`）

**定位**：不是 LiteLLM 的廉價版，是 BYOK 純粹主義。講到極致就是護城河。

**三個白地帶**（對手都沒做）：

1. 個人 / homelab 市場 —— 對手全在打企業
2. 「永遠 Apache 2.0、零 markup」的純粹主義聲量
3. Telegram / IM 派工 bot —— Claude Code + Codex + 自家 router 三方聚合是獨家

**三個功能缺口**（影響長期）：無 semantic cache、無 prompt management、無 Guardrails。若要補，**做成 plugin**，維持 OSS 純粹。

**長期不建議事項（§7.2，硬性）**：不加付費 tier、不做企業 sales、不做 SaaS、不走 Portkey 那種「代收費」路線。

### 5.3 商業文件的狀態

`BUSINESS_PLAN.md`（約 2000 行）與 `docs/STRATEGY.md` 的結論**有重疊也有摩擦** —— 前者的 12 個月 roadmap 排了 v0.2/v1.0 時程，後者的 §7.2 又禁止 SaaS。兩份尚未對齊。§8 把這列為待決策項。

---

## 6. 已知陷阱

**這一節是整個交接最有價值的部分。** 都是踩過、量過、寫成測試的坑。

### 6.1 health 與可用性

- **「endpoint 可連」不等於「可用」**。`health_check()` 只探 `GET /` 時，一台沒拉模型的 Ollama 會回 200、顯示綠燈，然後 `/api/chat` 404。現在 `providers/ollama.py` 探 `GET /api/tags` 並要求設定的 model 已 pull。**任何 provider 的 health 都必須證明 capability，不能只證 socket。**
- Ollama 模型比對規則：無 tag 的請求（`gemma4`）配任何 tag；有 tag 的（`gemma4:e2b`）必須完全相符。
- `ollama/` 前綴是 OpenAI-compat 端點的寫法，原生 `/api/chat` 會 404。`_normalize_model()` 在進來時剝掉，舊設定不用改。

### 6.2 Python 語言與標準庫

- **`http.server.HTTPServer.server_bind` 最後一行是 `socket.getfqdn(host)`** —— 反解 DNS。綁 `0.0.0.0` 很快，綁一個沒有 PTR 的具體位址會卡在 resolver 逾時。實測 10.014 秒。`scripts/status_server.py::_Listener` 顯式繞過它。**這個 repo 的鐵律：啟動路徑上不允許任何 DNS 查詢**（`primary_ipv4()` 的 docstring 早已寫明，只是漏了 `server_bind`）。
- **`socketserver` 呼叫 `get_request()` 的位置是 `serve_forever` 自己的執行緒**，在 `process_request()` 開 worker 之前。任何會阻塞的事（TLS 交握、DNS、檔案 IO）都不能放 `get_request()`，必須放 `process_request_thread()`。放錯會阻塞 accept。
- **socket 在 `__init__` 回傳時就已 LISTEN**。所以在「bind 完」與「`serve_forever` 開始」之間做的任何事，都會讓請求堆在核心 backlog 裡沒人 accept —— `ss -ltn` 看起來健康，訪客全部逾時。`start_listener()` 現在一 bind 就開 serve。**bind 即 serve。**
- **`BaseServer.shutdown()` 在 `serve_forever()` 沒跑過時會永久阻塞**。測試裡關伺服器要看 thread 有沒有真的啟動過。
- `socketserver` 把 `get_request()` 拋出的 `OSError` 視為「跳過這個連線」，**不打任何 log**。這會讓交握失敗變成無聲的 525。

### 6.3 bot / Telegram

- **`update_id` ≠ `message_id`**。`reply_to_message_id` 要的是後者。拿錯會回 `400 message to be replied not found`。**重現 400 時，永遠用 `curl -d` 打完全相同的 payload 並讀 response body 的 `description` 欄位** —— 它會告訴你真正原因。否則會往錯方向查好幾個小時（我們在 `parse_mode=null` 上浪費過）。
- Telegram `getUpdates` 的 409：httpx `AsyncClient` 連線池重用會讓 Telegram 誤判成並發。必須**每次 `getUpdates` 用全新的 `AsyncClient`** 加 `Connection: close`。共用一個 client 不行。
- `ALLOWED_CHAT_IDS` 空 = 全部拒絕。**不要改成預設放行。**
- `claude -p --output-format json` 的助理文字在 `result` 欄位，不是 `text`/`content`/`output`；`model` 是 `modelUsage` 的子鍵。
- `bot/.env` 的 `ANTHROPIC_API_KEY` 會與 `ANTHROPIC_AUTH_TOKEN` 衝突。已改名為 `ANTHROPIC_API_KEY_DISABLED_20260923`（保留不刪）。

### 6.4 多 agent / 測試

- `agents/state.py` 的 `TeamState` **每個可變 key 都要有 `Annotated[Type, reducer]`**，否則 LangGraph 在 `task` / `session_id` 拋 `InvalidUpdateError: Can receive only one value per step`。
- `config/capabilities.yaml` **必須**涵蓋 `agents/roles.py` 裡每個 `capability_required` 字串，否則拋 `no pool available for capability '...'`。七個角色需要：推理 / 程式碼 / 辯論 / 審查 / 驗證。
- `_PoolRunnable.invoke` 用 `ThreadPoolExecutor` 平行 fallback 時，**必須 `executor.shutdown(wait=False)`**，不能用 `with`。否則被一個還卡在 `pool.chat()` 的慢主選拖住，呼叫端無法回傳。
- `MagicMock(name="x")` 的 `.name` 是**另一個 mock**，不是字串 `"x"`。拿它當 dict key 會靜默錯。測試請用明確字串 key。
- 跑測試**只能用 `python3.12`**。

### 6.5 事件簿：狀態頁 522 / 525 / 10 秒死窗

值得整段讀，因為過程裡有**兩個被證實為錯誤的理論**，教訓比結果重要。

**症狀**：`https://khavis.kiddhsu.taipei` 回 522 → 修完冷啟動後變 525；本機 curl 有時 8 秒完全無回應。

**理論 1（錯）**：`srv.socket = ctx.wrap_socket(srv.socket, server_side=True)` 讓 GC 把 listening socket 的 fd 關掉。
**怎麼被推翻**：寫了一支獨立重現程式 —— `fileno()` 在 `gc.collect()` 之後仍然有效，TCP 連線也通。**理論錯誤。** `get_request()` 的改寫作為強化保留，但 docstring 裡那段錯誤的因果断言已經拿掉。

**理論 2（錯）**：`import google.generativeai` → `grpc` 的 C 擴充握住 GIL，把所有執行緒凍結。
**怎麼被推翻**：在 ECS 上量 —— import 耗時 0.816s，但背景 20ms tick 的**最大卡頓只有 35ms**。不足以解釋 8 秒。理論錯誤。

**過程中的第三個錯誤**：我把 TLS 交握放進 `get_request()`「修好」理論 1。但 `get_request()` 跑在 accept 執行緒上，這個改動**本身就是一個 bug**（每次交握阻塞 accept，backlog 只有 5）。後來移到 `process_request_thread()`。這是 `9377dfd`。

**真正的原因**：journal 的時間戳直接指認：

```
18:08:43.560  listening on http://0.0.0.0:80
18:08:53.574  listening on https://172.17.0.106:443   ← 10.014 秒後
18:08:53.576  GET /nope 404                            ← 立刻就通了
```

`HTTPServer.server_bind` 的 `socket.getfqdn("172.17.0.106")`（該位址無 PTR）卡了 10 秒。而 `main()` 是**建完所有 listener 才開始 serve**，所以 :80 已經 LISTEN 卻沒人 accept。這是 `fb70fae`。

**量測本身的教訓**（這些假象讓我們繞了遠路）：

| 假象 | 正解 |
| --- | --- |
| `curl` 失敗時不會寫輸出檔，讀到的是**上一次的舊檔** | 失敗就 `rm` 掉目標檔，或用 `curl -w` 直接吃時間 |
| `curl --max-time N` 逾時回 `code=000`，看起來像「連不上」 | 那是逾時，不是拒絕。看 `time_total` 是否 ≈ N |
| 等 `ss -ltn "sport = :443"` 會匹配到**別的行程**（tailscaled）佔的同埠 | 要比對完整位址（`172.17.0.106:443`） |
| shell 裡 `ssh ... 'python ...' &` 把 **ssh** 放背景，後面的 `curl` 跑在**本機** | curl 必須在同一個遠端 shell 內 |
| 重現不了 = 沒 bug | 是**環境差異**。高位埠測試綁 `0.0.0.0:8443` 成功，從沒走到退回具體位址那條路。重現失敗時先列出差異，不要下結論 |
| 日誌裡的 `BrokenPipeError` 像是服務 bug | 是自己的 `curl --max-time` 提早斷線，handler 才發現寫不出去 |

**結論性的方法論**：**用 journal 時間戳對齊，不要用推測。** 這次三個錯誤理論花了最多時間，而真正的證據一直是那兩行 `listening on` 的時間差。

---

## 7. 待辦清單

### 7.1 程式碼

1. **v0.2.0：token-aware 成本預算**（roadmap 的下一個）
2. **`providers/gemini.py` 從 EOL 的 `google.generativeai` 遷到 `google.genai`** —— 已知技術債。也是測試偶發 native crash 的來源。
3. 收編 codex 未追蹤檔案前，先修 §2.3 列的六個瑕疵
4. `BUSINESS_PLAN.md` 與 `docs/STRATEGY.md` 對齊（見 §8）
5. Claude-API pool 紅燈（餘額不足）
6. `setup_ollama.sh` 的 `pull_if_missing()` 用本地 `ollama pull`，應該改成 `curl POST $base/api/pull` 送到遠端 daemon（現行行為會拉到本機而非目標機）

### 7.2 需要使用者手動做的

1. **Surface 機器端**：裝／啟動 Ollama，設 `OLLAMA_HOST=0.0.0.0:11434`，開 Windows 防火牆 11434/TCP，`ollama pull qwen2.5:1.5b`。目前 11434 從 ECS 不通，`Ollama-Surface` 誠實顯示紅燈。**不要用 ping 探測 Surface**（Windows 丟 ICMP），要探 TCP 11434。
2. **`security@kiddhsu.taipei`**：Cloudflare Email Routing 已啟用、MX/SPF/DKIM 都齊了，**只差一條 routing rule** —— 需要一個真的目的信箱（要先驗證那個地址）。目前是唯一缺件。
3. **PGP**：GnuPG 2.5.24 已裝。建金鑰選 **(9) ECC and ECC → (1) Curve 25519**，期限 **0**。建完：
   - 公鑰：`gpg --armor --export security@kiddhsu.taipei`
   - 指紋：`gpg --fingerprint`
   - **`~/.gnupg/openpgp-revocs.d/` 裡的撤銷憑證一定要離線備份**
   - 替換 `SECURITY.md:50` 的 placeholder，把指紋發佈到 `https://khavis.kiddhsu.taipei/pgp.txt`
4. **撤銷憑證**：工作階段中貼過一組 Cloudflare Access Service Token 的 Client-ID（半個憑證、而且是錯的產品），建議到 Cloudflare 後台撤銷並改發正確的 API Token（權限 `Zone:Zone:Read` + `Zone:DNS:Edit`）。

### 7.3 已經不用做的（先前的建議已作廢或已完成）

- DNS：`bot` 與 `khavis` 兩筆 A record 都已存在、已 proxied
- Email Routing 的 MX / SPF / DKIM / DMARC：都已設定
- ufw 80/443：已開啟
- ~~Cloudflare SSL 改 Flexible~~ —— **不要做**。`Full` 才是對的，見 §9。

---

## 8. 待決策（不是工程問題，要人決定）

1. **codex 的未追蹤檔案要不要收進 repo**（`docs/STRATEGY.md` 等）。我的建議：收，但先修 §2.3 的六個瑕疵。
2. **`RELEASE_CHECKLIST.md:54` 的 Stripe** vs `docs/STRATEGY.md` §7.2 的「不做 SaaS」。我的建議：**不開 Stripe 帳號**，改用 GitHub Sponsors，並刪掉／替換那一行。Stripe 需要帳戶，且與策略文件直接衝突。
3. **`BUSINESS_PLAN.md` 怎麼處理** —— 收斂進 `STRATEGY.md`、標為歷史文件、或重寫。
4. **Route to DERP 還是優化 direct connection** —— 三個 Tailscale 節點目前全走 DERP(hkg)，RTT 160–290ms。拿到 direct path 會是很大的延遲改善。

---

## 9. 工作守則（這個 repo 的硬性慣例）

### 9.1 Git 與對外

- **commit message 不要加 `Co-Authored-By: Claude Code` 尾條**。這是使用者的明確指示，優先於任何預設慣例。
- PR 描述結尾要加：
  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  ```
- Git 作者身分：`kiddhsu5 <kiddhsu5@users.noreply.github.com>`
- repo 位址：`github.com/kiddhsu5/khavis`（公開，Apache 2.0）

### 9.2 安全紅線（違反任一項都是事故）

1. **GitHub 帳號 `kiddhsu` 不是使用者本人 —— 絕對不要碰。** 使用者只有 `kiddhsu5`。
2. **`.env` 永遠不要 commit**。`.gitignore` 已涵蓋，但要自己確認。
3. **任何 token、API key 都不要出現在工具輸出裡** —— 連前綴（例如 `k[:6]`）都不行。只能回報「有／沒有」和長度。
4. `BOT_TOKEN` 即使部分也不要印。只檢查 `bool(os.environ.get('BOT_TOKEN'))`。
5. 用 `gh secret set` 設 secret 時要用 `printf '%s'`，**不要用 `echo`** —— 尾隨換行會破壞驗證。
6. **不要掃 macOS Keychain 找雲端憑證。**
7. **不要把 Cloudflare 區的 SSL 模式設成 `Flexible`。** 分類器曾對此正確地攔下：Flexible 會對**整個 kiddhsu.taipei 區**停用 CF→origin 的加密。`Full` 已經可以吃 origin 的自簽憑證，不需要降級。目前是 `full`，保持。
8. 任何 API token／Access Service Token 只能存在有 `chmod 600` 的本地暫存檔，**不要寫進記憶檔或 repo**。
9. 防火牆／對外服務的變更要人核准，不要自行繞過。

### 9.3 環境

- 測試與工具一律 `python3.12`（本機 `python3` 是 3.9.6，不適用）
- 本機 Mac 沒有專案 venv；ECS 上有 `.venv`
- 不要用 ICMP 探測 Tailscale 節點的存活

---

## 10. 一句話給接手的人

這個 repo 的程式碼品質是好的（290 tests、0 lint、0 type errors），**風險都在運維細節和陷阱上**。§6 裡每一條都對應一個實際發生過、量產過、寫成測試的 bug。讀完 §6 再動手，可以省掉好幾個小時。
