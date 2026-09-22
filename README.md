# orca-collab

用 [Orca](https://github.com/stablyai/orca) 建立可追蹤的 agent 派工：single 模式由 operator 直接監督一名 worker；collab 模式由 operator 派一名 orchestrator，再由它組織實作者與獨立驗證者。skill 固化 preflight、briefing、長等待、驗收和生命週期收尾。

Use [Orca](https://github.com/stablyai/orca) for traceable agent delegation. In single mode an operator supervises one worker; in collab mode the operator dispatches one orchestrator, which coordinates implementation and independent verification. The skill packages preflight, briefing, long waits, acceptance, and lifecycle cleanup.

## 安裝 Install

```bash
git clone https://github.com/fredchu/orca-collab ~/dev/orca-collab
bash ~/dev/orca-collab/scripts/install.sh
```

安裝器可重跑，建立三個 symlink：Claude Code 的 `~/.claude/skills/orca-collab`、pi 的 `${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/skills/orca-collab`，以及 Codex（pi 也會讀）的 `~/.agents/skills/orca-collab`。若既有路徑指向別處，安裝器會報錯而不覆蓋。

The idempotent installer creates three links: `~/.claude/skills/orca-collab`, `${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/skills/orca-collab`, and the Codex-compatible `~/.agents/skills/orca-collab` (also discovered by pi). Existing wrong targets are reported and never overwritten.

## 需求 Requirements

- macOS 上已安裝並啟動 Orca CLI/runtime
- Bash、Python 3、Git
- `pi`（preflight 會檢查）
- 可選：`agent-orch`，用來顯示 Claude/Codex 額度；找不到時標 SKIP
- launchd 安裝需要 `plutil`；Tailscale IP 可自動偵測或用 `--ip` 指定

## 客製化 Configuration

| env | default | 說明 |
|---|---|---|
| `ORCA_COLLAB_DIR` | `~/.claude/collab` | briefing 與 findings 的根目錄 |
| `ORCA_COLLAB_REPO` | 無 | preflight 的目標 repo；也可用 `--repo` |
| `PI_CODING_AGENT_DIR` | `~/.pi/agent` | pi skill 根目錄 |
| `ORCA_CLI_COMMAND` | `orca` | Orca CLI 命令（由 Orca managed session 提供時優先） |

## 使用 Usage

對 agent 說「用 Orca 派」、「用 Orca 開三席」、「Orca 現況」或「你當 operator」。它會依 `SKILL.md` 選 single／collab，先執行 preflight，再建立 Run、等待 typed messages、獨立驗收並逐席收尾。

```bash
python3 scripts/bootstrap.py --topic fix-parser --repo /abs/repo --mode single
python3 scripts/bootstrap.py --topic infra-review --repo /abs/repo --mode collab \
  --sessions 3 --roles orchestrator,implementer,adversarial-verifier
```

Ask your agent to “use Orca to dispatch” or “act as operator.” It chooses single or collab mode, performs preflight, creates the Run, waits for typed messages, independently verifies results, and settles every dispatch.

## launchd

```bash
bash launchd/install-launchd.sh --ip <TAILSCALE_IP> --out /tmp/LaunchAgents
# 確認產物後，再由 operator 執行腳本印出的 launchctl bootstrap 指令。
```

安裝腳本只產 plist、lint 並印指令，**不會**執行 bootstrap／bootout。

### 注意 Notice

Orca 桌面版與 `orca serve` 共用 single-instance lock；plist 以 `KeepAlive = true` 守住永不主動退出的包裝腳本，由腳本避開桌面版並重試 serve。plist 會寫死當下的 Tailscale IP；IP 變更後要重跑 `install-launchd.sh`。`--pairing-address` 只改變告訴客戶端的位址，serve 本身仍綁 `0.0.0.0`。

**硬規則：serve 模式下只准關視窗，不准按 ⌘Q。** 關視窗時 serve 仍存活；⌘Q 會把 serve 一起殺掉（Orca issue #15537；修正 PR #15560 截至 2026-09-21 尚未合併）。要真正停止 serve，執行 `launchctl bootout gui/$(id -u)/com.user.orca-serve`。

serve 跑著時開桌面版：不是第二個程序，serve 程序自己開出視窗（Orca issue #15537，operator 已查證）。關視窗（⌘W）serve 繼續活；⌘Q 會把 serve 一起結束，退出碼 0（原始碼 1.4.197 `main-process-quit.ts` 推論，PR #15560 未合併），包裝腳本會在 5 秒後把 serve 拉回來。launchd 真載入、FDA 讀 iCloud 兩項本輪未實測，由 operator 用正式 label 切換時驗。

Opening the desktop app while serve is running reuses the serve process and opens its window (Orca issue #15537): closing the window (⌘W) keeps serve alive, while ⌘Q exits it with code 0 and the wrapper restarts it after five seconds; real launchd loading and iCloud FDA access remain for the operator to verify with the production label.

## 平台支援 Platform support

| 部分 | macOS | Windows |
|---|---|---|
| `SKILL.md`、`references/`（operator 流程） | ✅ 實測 | ✅ 應可（全走 `orca` CLI；未實測） |
| `scripts/preflight.sh`、`orca-wait.sh`、`bootstrap.py` | ✅ 實測 | ⚠️ 在 Git Bash 跑，未實測 |
| `scripts/install.sh`（symlink） | ✅ | ✅ Git Bash 開啟開發者模式或以管理員執行即可使用；無法建立符號連結時回報 ERROR，不再複製 |
| `launchd/` | ✅ 實測 | ❌ 不適用。改用工作排程器，或桌面版開著就不需要 serve |
| 「serve 模式不准 ⌘Q」 | ✅ 查證 | ⚠️ Windows 的退出／單一實例行為未驗 |

Windows 的支援請看 issue #1；歡迎補 PowerShell 版安裝與工作排程器範本。

macOS is the tested platform. On Windows the operator flow (`SKILL.md`, `references/`) should work as-is since it only calls the `orca` CLI; `install.sh` works in Git Bash with Developer Mode enabled (or elevated), and otherwise reports ERROR instead of copying; other bash helpers are untested and `launchd/` does not apply — see issue #1.

## 測試 Tests

```bash
python3 -m pytest -q
```

測試使用暫存 HOME／輸出目錄，不呼叫真 Orca、不載入 launchd，也不寫真 `~/Library/LaunchAgents`。

Tests use temporary homes and output directories. They do not invoke a real Orca runtime or load launchd jobs.

## License

MIT
