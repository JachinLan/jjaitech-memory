#!/bin/bash
# Local stdio launcher; no download, no shell eval, no stdout except selected script.
set -eu
jj_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
jj_python=''
jj_probe() {
  case "$1" in *WindowsApps*|/usr/bin/python3|'') return 1 ;; esac
  if [ -x "$1" ] && "$1" -X utf8 -c 'import sys,sqlite3; assert sys.version_info >= (3,9); sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE probe USING fts5(x)")' >/dev/null 2>&1; then
    jj_python=$1; return 0
  fi
  return 1
}
# Installation's validated interpreter is fastest; a moved runtime falls back locally.
if [ -f "$jj_root/.runtime-python-paths" ]; then
  while IFS= read -r jj_candidate; do
    jj_candidate=${jj_candidate%$'\r'}
    if jj_probe "$jj_candidate"; then break; fi
  done < "$jj_root/.runtime-python-paths"
fi
jj_config=${CODEBUDDY_CONFIG_DIR:-"$HOME/.workbuddy"}
if [ -f "$jj_root/.runtime-config-root" ]; then IFS= read -r jj_config < "$jj_root/.runtime-config-root"; jj_config=${jj_config%$'\r'}; fi
if [ -z "$jj_python" ]; then
  for jj_candidate in "$jj_config"/binaries/python/versions/*/bin/python3 "$jj_config"/binaries/python/versions/*/python.exe "$jj_config"/binaries/python/versions/*/python/python.exe; do
    if jj_probe "$jj_candidate"; then break; fi
  done
fi
if [ -z "$jj_python" ]; then
  for jj_name in python3 python; do
    jj_candidate=$(command -v "$jj_name" || true)
    if jj_probe "$jj_candidate"; then break; fi
  done
fi
if [ -z "$jj_python" ]; then
  echo 'jjaitech-memory: no usable local Python 3.9+ with SQLite FTS5. Re-run the installer; no data was removed.' >&2
  exit 1
fi
case "${1:-}" in
  mcp) shift; exec "$jj_python" -X utf8 "$jj_root/scripts/memory_mcp.py" "$@" ;;
  *) exec "$jj_python" -X utf8 "$jj_root/scripts/memory.py" "$@" ;;
esac
