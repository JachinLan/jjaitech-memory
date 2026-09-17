# jjaitech-memory

Local-first personal/work memory plugin for WorkBuddy, by JJ AI TECH.

**Windows pilot release.** The core has Mac unit and model tests. Windows CI validates code and PowerShell syntax; it does not prove authenticated WorkBuddy desktop end-to-end behavior. Start with one pilot computer.

## Install on Windows

First open WorkBuddy and sign in with your own account. Then paste this single command into **Windows PowerShell** (not cmd.exe):

```powershell
irm https://raw.githubusercontent.com/JachinLan/jjaitech-memory/v1.2.0-rc.2-online.1/install.ps1 | iex
```

This version-pinned launcher verifies the release ZIP SHA256 before executing the installer. Read `install.ps1` and `jjaitech-memory/distribution/bootstrap-windows.ps1` before running if you want to inspect the installation actions. Use only links from this repository; do not change a checksum to silence a mismatch.

The installer asks for YES consent, discovers the actual WorkBuddy CLI, installs missing Python/Node/Git through WinGet when available, asks you to quit WorkBuddy, and registers the plugin. Dependency license/UAC/enterprise-policy prompts remain visible. No silent agreement acceptance, force-killing tasks, or execution-policy changes. If WinGet or required permissions are unavailable it stops with instructions; it cannot promise zero interaction on every computer.

## What changes

- Installs local plugin code under your WorkBuddy configuration directory.
- Adds only your own `~/AI-Wiki` to the existing WorkBuddy sandbox write list. All WorkBuddy tools can write that directory, not just this plugin.
- Stores per-person Raw dialogue, structured facts and Markdown locally.
- Lets your current WorkBuddy cloud model process new dialogue/relevant retrieved excerpts. This is not offline inference.
- Does not add an external model API, upload Wiki files, copy another person's login or enable automatic sharing.
- Keeps installation receipts/configuration backups. Runtime dependencies installed through WinGet are not uninstalled on a later plugin failure.

## Check after installation

Reopen WorkBuddy. Give one true low-sensitivity work preference; then ask about it in a NEW conversation without repeating the answer. Check `~/AI-Wiki/Raw` and `Work`. A fictional role-play is intentionally excluded from production memory and is not an adequate production acceptance test.

```powershell
$MemoryScript = Join-Path $env:USERPROFILE '.workbuddy/local-marketplaces/jjaitech-local/jjaitech-memory/scripts/memory.py'
py -3 -X utf8 $MemoryScript doctor
# Disable without deleting data:
py -3 -X utf8 $MemoryScript disable
# Re-enable:
py -3 -X utf8 $MemoryScript enable
```

If Python was installed without the `py` launcher, invoke the actual Python executable shown by the installer instead. Custom configuration directories require the manual installer `--config-dir` option.

## Limits

Hook/model outages, unfinished turns and shutdowns can leave pending work. Semantic extraction can be wrong: quoted text is not a guarantee the fact is correct. Quotes/contracts and published company assets need review. Manual page conflicts are preserved, not automatically merged. One turn processes one bounded chunk; no idle backlog worker. Large-history retrieval, company access control, mailbox/thread/attachment ingestion, independent backups and native Windows desktop acceptance remain work to complete.

Explicit work-sharing exports exclude Personal/Raw/excerpts but still need review of fact text. Imported shared assets are stored separately and are not automatically searched. Never send your private-backup ZIP to colleagues as a work-share bundle.

## Development

```text
python -m unittest discover -s jjaitech-memory/tests -v
```

Only allowlisted code is packaged. Release ZIPs do not include personal Wikis, credentials or production conversation logs. Source publication does not grant any recipient access to a contributor's Wiki.

## Public command installation evidence

[Exact published command test — passed](https://github.com/JachinLan/jjaitech-memory/actions/runs/35191533767): ran the published online.1 command twice on a disposable Windows runner using the actual CLI 2.137.1 extracted from Tencent-signed WorkBuddy 5.5.6.38337834. Verified plugin registration, source hashes, permission idempotency, unrelated settings preservation and local Raw hook deduplication. The test supplied YES consent and had Python/Node/Git already installed. It used an empty configuration, no login and no model calls. It does **not** establish Windows desktop memory save/recall, fresh dependency installation, or compatibility with every company endpoint policy.

Before distribution, one employee-owned test computer must still verify a true low-sensitivity work preference is saved, recalled in a new conversation, and recalled again after a full WorkBuddy restart. Check actual Raw/Work files and doctor output, rather than relying on the model saying it remembered.
