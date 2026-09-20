#!/bin/bash
set -eu
jj_package=${1:?Pass the extracted package root}; shift
if [ "$(uname -s)" != Darwin ]; then echo 'Use the Windows installer on Windows.' >&2; exit 1; fi
jj_config=${WORKBUDDY_CONFIG_DIR:-"$HOME/.workbuddy"}
if [ ! -d "$jj_config" ]; then echo 'Open WorkBuddy and sign in first, then retry.' >&2; exit 1; fi
jj_python=''
for jj_candidate in "$jj_config"/binaries/python/versions/*/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 "$(command -v python3 || true)"; do
  # Apple's stub can open an unexpected developer-tools installer; do not invoke it.
  case "$jj_candidate" in /usr/bin/python3|'') continue ;; esac
  if [ -x "$jj_candidate" ] && "$jj_candidate" -X utf8 -c 'import sys,sqlite3; assert sys.version_info >= (3,9); sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE p USING fts5(t)")' >/dev/null 2>&1; then jj_python=$jj_candidate; break; fi
done
if [ -z "$jj_python" ]; then
  echo 'No usable Python 3.9+ with SQLite FTS5 found. Let WorkBuddy finish runtime setup, or install Python from https://www.python.org/downloads/macos/ then retry. No Homebrew or developer tools are installed automatically.' >&2
  exit 1
fi
jj_installer="$jj_package/jjaitech-memory/scripts/install_local.py"
if [ ! -f "$jj_installer" ]; then echo 'Incomplete package.' >&2; exit 1; fi
# --check remains read-only and can run while the desktop is open.
"$jj_python" -X utf8 "$jj_installer" --check "$@"
for jj_arg in "$@"; do if [ "$jj_arg" = '--check' ]; then exit 0; fi; done
printf '%s\n' 'Current WorkBuddy cloud model processes selected text; Wiki files remain local.' 'This grants all WorkBuddy tools write access to YOUR AI-Wiki and three named memory MCP tools.' 'Finish tasks and quit WorkBuddy before installing. Existing settings and Wiki are preserved.'
printf 'Type YES to continue: '
IFS= read -r jj_consent
if [ "$jj_consent" != YES ]; then echo 'Cancelled; no plugin changes.'; exit 1; fi
"$jj_python" -X utf8 "$jj_installer" "$@"
