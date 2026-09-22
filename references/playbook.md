# Orca operator playbook

這是可攜式速查，不含個人 IP、帳號或本機 repo 路徑。實際旗標以當前 `orca skills get orchestration` 和 `--help` 為準。

## 資料模型：repo 只是容器，worktree 才是任務

```
Repo（專案）          登錄進 Orca 的容器；也可以是沒有 git 的資料夾（資料夾型專案）
 └ Worktree           任務單位：一個任務一個分支一個目錄；手機上一列就是一個
    └ Terminal        一個 worktree 可開多個
       └ Agent        一個終端機跑一個 Claude Code／pi／Codex
```

- 編排層的 Run／Task／Dispatch 綁**終端機**，不綁 repo；`worker-start` 能用 `--repo`／`--worktree`／`--host` 指到別的 repo 或機器（跨 repo 未實測）。
- **沒有 git 的資料夾只有一個工作區**（原始碼 `repo-worktrees.ts` 對 folder 型只回傳資料夾本身）：能開終端機與 agent，不能開第二個 worktree，所以無法平行隔離。CLI `orca repo add` 直接拒絕非 git 路徑。要平行就在那個資料夾 `git init`（不用 remote），Orca 偵測到 `.git` 會自動升級成 git 型專案。
- 移除 repo 登錄沒有 `repo rm`：`orca project setups --json` 找 setup id → `orca project setup-delete --setup <id>`。

## 三種使用形態

| 形態 | 啟動 | 用途 |
|---|---|---|
| 桌面程式 | `open -a Orca` | 人在電腦前看 GUI |
| 網頁／手機 | `orca serve` 印出的配對 URL | 遠端查看與回話；配對碼視為密碼 |
| 背景服務 | `ORCA_TELEMETRY_DISABLED=1 orca serve --pairing-address <TAILSCALE_IP>` | agent operator 的預設 |

Orca 沒有互動式 TUI。狀態以 CLI JSON、typed messages 與 liveness 為準。

## 起 serve 與 single-instance 坑

```bash
ORCA_TELEMETRY_DISABLED=1 orca serve --pairing-address <TAILSCALE_IP>
orca status --json  # runtime.state == ready 才算成功
```

serve 通常綁所有介面；不要暴露在公網。桌面程式與 serve 共用 single-instance lock：同一 user-data profile 只能有一個 Orca 程序。另一個實例可能只留下 `[single-instance] Another Orca instance is already running` 就以退出碼 3 結束（Orca 原始碼 1.4.197 `single-instance-lock.ts`；安裝版 1.4.205 未逐行對）。不要在沒有正面確認與授權時停止既有 runtime；`unverifiable` 不等於 exited。

**硬規則：serve 模式下只准關視窗，不准按 ⌘Q。** 關視窗不會停 serve；⌘Q 會把 serve 一起殺掉（Orca issue #15537；修正 PR #15560 截至 2026-09-21 尚未合併）。要停用 launchd 管理的 serve，執行 `launchctl bootout gui/$(id -u)/com.user.orca-serve`。

## 基本編排與旗標表

```bash
C=$(orca terminal create --worktree current --command zsh --json | jq -r .result.terminal.handle)
R=$(orca orchestration run-create --objective "<objective>" --from "$C" --json | jq -r .result.run.id)
orca orchestration worker-start --spec "<five-field task>" --worktree current --run "$R" --from "$C" --agent claude --json
orca orchestration check --run "$R" --terminal "$C" --wait --types "worker_done,escalation,question" --timeout-ms 300000 --json
```

| 指令 | 主管 handle 旗標 |
|---|---|
| `run-create`, `worker-start`, `reply` | `--from <handle>` |
| `check` | `--terminal <handle>`，不是 `--from` |
| `worker-release`, `worker-list` | 不收主管 handle；用 dispatch 或 run |

補充：

- `new-child` 必須帶 `--name`。
- 信任框造成 `agent_readiness` 失敗後，先處理信任框，再以 `--task <task_id> --retry-of <dispatch_id> --terminal <handle> --worktree name:<wt>` 重試；不能再帶 `--spec`。
- 同一名 proven worker 接新工作時，以新 spec 搭配原 terminal 與 worktree。
- `worker-start --model` 不支援 pi。pi 先 `terminal create --command "pi --model <model> --thinking <level>"`，TUI 就緒後用 `worker-start --terminal <handle>` 收編。
- release 只在已接受 settlement 後做；最後用 `worker-list --run <R> --terminal-state reclaimable --json` 確認為零。

## 首次信任框

首次進新 repo 可能卡在預設選中「No, exit」：

```bash
orca terminal read --terminal <handle> --json
orca terminal send --terminal <handle> --text $'\e[B' --json
orca terminal send --terminal <handle> --text $'\r' --json
```

先讀畫面確認再送鍵；不要把 `terminal wait --for tui-idle` 當作任務完成。

## `check --wait` 心跳與解析

等待期間 stdout 可能有多個 JSON 物件：

```json
{"_keepalive":true,"_heartbeat":true,"elapsedMs":15003}
{"id":"...","ok":true,"result":{"messages":[],"timedOut":true}}
```

最後一個非 keepalive JSON 才是結果。不要用 `grep -v _keepalive`：結果 message 的 body 可能合法含有字串 `_keepalive`。應逐個 JSON 物件 `raw_decode`，只丟掉根物件 `obj.get("_keepalive") is true` 的物件。`scripts/orca-wait.sh` 已封裝這個行為並保存完整 stdout。

## 訊息通道三個實測坑（2026-09-22）

同一輪協作裡三個都踩到，每個都讓 operator 以為「沒消息＝沒事」。

**1. `send --to run:<id>` 回 `ok: true` 但對方收不到。** worker 明確回報 `check` 與 `inbox` 都是空的。
同一段內容改用 `reply --id <msg_id>` 送就到了。**`ok` 只證明送出成功，不證明送達。**
operator 對 worker 的指示一律用 `reply`；要主動開話題就先讓對方送一則 status 再回覆它。

**2. 長訊息會被截斷，而且對方不會說。** 一則含四個編號要點的回覆，worker 只收到第 3、4 點，
自己送 typed question 問「第 1、2 點是什麼」才暴露。**指示寫短、一則一個主題**；
內容多就落檔案、訊息只帶路徑。

**3. 等待器只看席位狀態會漏接 typed question。** `worker_done,escalation` 不含 `question`，
worker 問了十分鐘沒人回，自己選了保守做法繼續。**掛等待一律含 `question`**
（`--types worker_done,escalation,question`），並在任務書寫明「operator 會盯訊息，請等回覆」。

## 砍掉等待器的客戶端不會註銷伺服器端的等待者

`pkill` 掉跑著 `check --wait` 的程序之後，新的等待器會被 `waiter_exists` 拒絕：
`Run <id> already has an active actionable waiter`。伺服器端的註冊要等原本的 `--timeout-ms`
到期才釋放，設了 55 分鐘就是擋 55 分鐘。

繞法是**不帶 `--wait` 的輪詢**：`check --peek --types ...` 不註冊等待者，包成
`until ... ; do sleep 60; done` 的背景任務，效果一樣而且可以隨時重起。

連帶紀律：**Bash 背景任務要用 harness 的 `run_in_background`，不要 `nohup ... &`**。
後者 harness 追蹤不到，跑完不會通知，等於掛了一個永遠不會叫醒你的把手。

## 巢狀關閉與 B 路線

預設 `nestedWorkerMaxDepth=1` 時，Run 0 worker 不能再啟動 depth 2 worker。不要偷偷改全域設定。B 路線：orchestrator 用 `terminal create` 開席、`terminal send` 注入任務書；下層用：

```bash
orca orchestration send --from <child-handle> --to run:<orchestrator-run> \
  --type status --subject "succeeded: ..." --body "<summary and evidence>" --json
```

orchestrator 以 `check --wait --types "status,question,escalation"` 收訊。這些席位沒有 worker_done／worker-release；收尾要明送角色作廢，再 `terminal close`。

## 任務書五欄

每份 spec 必須自足：

1. **Target**：檔案、元件或環境。
2. **Change**：具體要產生的結果。
3. **Constraints**：不變量、相容性與禁止事項。
4. **Ownership**：可改範圍與協作邊界。
5. **Observable acceptance**：可重跑的測試、輸出與證據。

## 回報格式

每席回報三樣：結論一句、證據路徑／實際輸出、任務書或對方哪裡錯。結果要明示 `succeeded` 或 `failed`；失敗不可只藏在散文。operator 仍須自己驗收。

## 長等待

使用單一阻塞等待作為叫醒把手，而非 sleep 輪詢：

```bash
scripts/orca-wait.sh --run <R> --terminal <C> \
  --types worker_done,escalation,question --timeout-ms 3300000 --out <raw-log>
```

逾時只是 checkpoint。連續空回後用 worker-list 與 terminal read 盤點；只有正面退出證據才可 stop、abandon 或 retry。
