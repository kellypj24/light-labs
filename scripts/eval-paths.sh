#!/usr/bin/env bash
# Changed file names on stdin; exits 0 when one is under a prefix in .github/eval-paths.txt,
# that is, when the Eval harness has to run. CI's Changes job and `just check` both ask here.
set -euo pipefail
cd "$(dirname "$0")/.."
patterns=$(grep -v -e '^#' -e '^$' .github/eval-paths.txt | sed 's/[.]/\\./g; s/^/^/')
grep -q -E -e "$patterns"
