# Changelog

## Unreleased

- 修正 Windows 安裝器複製目錄與既有 .lnk 捷徑的假成功，驗證符號連結並依失敗原因提供提示。

## 0.1.1 - 2026-09-21

### 文件
- playbook 新增「資料模型」段：repo→worktree→terminal→agent 四層；資料夾型專案只有一個工作區，要平行先 `git init`；移除登錄用 `project setup-delete`
- README 平台支援表（macOS 實測；Windows 對應做法見 issue #1）

### 修正
- preflight 對非 git 路徑的 FAIL 訊息說明原因與解法
- `install-launchd.sh` 與測試在沒有 `plutil` 的平台改用 `plistlib`（CI Linux 紅燈）


## 0.1.0 - 2026-09-21

### Added
- `orca-collab` operator skill with single and collab modes
- portable playbook and briefing template
- preflight, bootstrap, idempotent installer, and robust Orca wait parser
- launchd plist generator for `orca serve`
- bootstrap, wait-parser, preflight, and launchd tests
