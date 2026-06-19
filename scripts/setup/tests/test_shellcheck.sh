#!/usr/bin/env bash
set -euo pipefail

if ! command -v shellcheck >/dev/null 2>&1; then
    echo "shellcheck non installato"
    exit 1
fi

fail=0
for f in scripts/install.sh scripts/setup/lib/*.sh scripts/setup/*.sh; do
    if [[ -f "$f" ]]; then
        echo "Checking $f"
        if ! shellcheck -x "$f"; then
            fail=1
        fi
    fi
done

if [[ $fail -eq 0 ]]; then
    echo "All shellcheck tests passed."
else
    echo "Some shellcheck tests failed."
    exit 1
fi
