#!/usr/bin/env bash
# Run npm for this frontend from a mirror on the local disk.
#
# Why: the repository lives in a Google Drive folder, whose filesystem rejects junctions and symbolic links and makes
# npm fail (EBADF) while it writes node_modules. So Node tooling runs in C:\Users\<you>\.cache\agentqa-studio\
# frontend-work: this script mirrors frontend/ there (everything but node_modules, dist and reports), runs npm, and
# copies back what the run produced (dist/, package.json, package-lock.json, test results).
#
#     bash frontend/local-node.sh install
#     bash frontend/local-node.sh run build
#     bash frontend/local-node.sh test
#
# On Linux/macOS/CI the repo is on a normal disk: run npm in frontend/ directly.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
WORK="${AGENTQA_FRONTEND_WORK:-$HOME/.cache/agentqa-studio/frontend-work}"
mkdir -p "$WORK"

win() { cygpath -w "$1"; }
# MSYS_NO_PATHCONV stops Git Bash from turning robocopy's /MIR-style switches into paths. robocopy exits 0-7 on success.
rc() { local status=0; MSYS_NO_PATHCONV=1 robocopy "$@" >/dev/null || status=$?; [ "$status" -le 7 ]; }
mirror() { rc "$(win "$1")" "$(win "$2")" /MIR /XD node_modules dist test-results playwright-report .vite /NFL /NDL /NJH /NJS /NP; }
copy_back() {
  for f in package.json package-lock.json; do [ -f "$WORK/$f" ] && cp "$WORK/$f" "$SRC/$f"; done
  for d in dist test-results playwright-report; do
    [ -d "$WORK/$d" ] && rc "$(win "$WORK/$d")" "$(win "$SRC/$d")" /MIR /NFL /NDL /NJH /NJS /NP
  done
  return 0
}

mirror "$SRC" "$WORK"
cd "$WORK"
status=0
npm "$@" || status=$?
copy_back
exit "$status"
