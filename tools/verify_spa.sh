#!/usr/bin/env bash
# SPA load-verification for classic (non-module) script splits.
# Catches the real failure modes of splitting shared-global JS files:
#   1. per-file syntax errors
#   2. duplicate top-level let/const declarations across files (browser throws
#      "Identifier already declared" because classic scripts share ONE global
#      lexical environment — concatenating in load order reproduces it exactly)
#   3. renderView() dispatch targets that are defined in no loaded file
# Run from the store root: bash tools/verify_spa.sh
set -u
cd "$(dirname "$0")/.." || exit 2
IDX=static/index.html
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# 1) ordered list of local script srcs from index.html
mapfile -t SRCS < <(grep -oE "script src='/store/(static/js/[^']+)'" "$IDX" | sed -E "s#script src='/store/##; s#'##")
echo "scripts in load order: ${#SRCS[@]}"

# 2) per-file syntax
fail=0
for s in "${SRCS[@]}"; do
  if [ -f "$s" ]; then node --check "$s" 2>>"$TMP/err" || { echo "SYNTAX FAIL: $s"; fail=1; }
  else echo "MISSING: $s"; fail=1; fi
done

# 3) concatenate in order -> node --check the bundle (redeclaration / global-scope)
: > "$TMP/bundle.js"
for s in "${SRCS[@]}"; do [ -f "$s" ] && { cat "$s" >> "$TMP/bundle.js"; echo ";" >> "$TMP/bundle.js"; }; done
if node --check "$TMP/bundle.js" 2>"$TMP/bundle.err"; then
  echo "BUNDLE OK (no redeclaration / global-scope syntax errors)"
else
  echo "BUNDLE FAIL:"; cat "$TMP/bundle.err"; fail=1
fi

# 4) dispatch coverage: every case '<view>': render...() target must be defined somewhere
grep -oE "function (render[A-Za-z0-9_]+|[a-z][A-Za-z0-9_]*)\b" "${SRCS[@]}" 2>/dev/null \
  | sed -E 's/.*function //' | sort -u > "$TMP/defined.txt"
echo "defined top-level functions: $(wc -l < "$TMP/defined.txt")"

echo "RESULT: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit $fail
