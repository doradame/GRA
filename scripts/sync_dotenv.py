#!/usr/bin/env python3
"""Reformat .env using .env.example as a commented template.

Preserves existing real values from .env while adding comments and sections
from .env.example. Variables present in .env but missing from .env.example are
kept at the bottom of the file so no custom setting is lost.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"


def parse_env(path: Path) -> dict[str, str]:
    """Parse a key=value env file, ignoring comments and blank lines."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                values[key.strip()] = value.strip()
    return values


def main() -> int:
    if not EXAMPLE_FILE.exists():
        print(f"Template not found: {EXAMPLE_FILE}", file=sys.stderr)
        return 1

    existing = parse_env(ENV_FILE)

    # Read the example as a list of lines so we can inject real values while
    # keeping comments and section separators.
    with EXAMPLE_FILE.open("r", encoding="utf-8") as f:
        template_lines = f.readlines()

    output_lines: list[str] = []
    seen_keys: set[str] = set()

    for line in template_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            output_lines.append(line)
            continue
        if "=" in stripped:
            key, _, placeholder = stripped.partition("=")
            key = key.strip()
            placeholder = placeholder.strip()
            seen_keys.add(key)
            value = existing.get(key, placeholder)
            output_lines.append(f"{key}={value}\n")
        else:
            output_lines.append(line)

    # Append any variables from .env that are not in the example.
    extra = {k: v for k, v in existing.items() if k not in seen_keys}
    if extra:
        output_lines.append("\n# -----------------------------------------------------------------------------\n")
        output_lines.append("# Additional variables from the previous .env (not in .env.example)\n")
        output_lines.append("# -----------------------------------------------------------------------------\n")
        for key, value in sorted(extra.items()):
            output_lines.append(f"{key}={value}\n")

    # Write atomically.
    tmp = ENV_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.writelines(output_lines)
    os.replace(tmp, ENV_FILE)

    print(f"Synchronized {ENV_FILE} from {EXAMPLE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
