#!/usr/bin/env python3
"""
Verification script for AGENTS.md documentation architecture.
Checks:
1. Relative Markdown link validity across root and docs/agents/ documentation.
2. Formatting and whitespace hygiene (no trailing whitespace, proper trailing newline).
"""

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DOCS_TO_CHECK = [
    "AGENTS.md",
    "docs/agents/orchestration.md",
    "docs/agents/handoff.md",
    "docs/agents/project-constraints.md",
    "docs/agents/issue-tracker.md",
    "docs/agents/triage-labels.md",
    "docs/agents/domain.md",
    ".scratch/agent-guidance/verification-report.md",
]


def check_links():
    link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    broken_links = []
    total_links = 0

    for rel_path in DOCS_TO_CHECK:
        full_path = REPO_ROOT / rel_path
        if not full_path.exists():
            broken_links.append(f"Missing doc file: {rel_path}")
            continue

        content = full_path.read_text(encoding="utf-8")
        parent_dir = full_path.parent

        for match in link_pattern.finditer(content):
            label, target = match.groups()
            # Skip external URLs and anchor-only links
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            # Strip anchor
            target_clean = target.split("#")[0].strip()
            if not target_clean:
                continue

            total_links += 1
            resolved_path = (parent_dir / target_clean).resolve()
            if not resolved_path.exists():
                broken_links.append(f"In {rel_path}: Broken link [{label}]({target}) -> {resolved_path}")
            else:
                print(f"[OK link] {rel_path} -> {target_clean}")

    return total_links, broken_links


def check_whitespace():
    whitespace_issues = []

    for rel_path in DOCS_TO_CHECK:
        full_path = REPO_ROOT / rel_path
        if not full_path.exists():
            continue

        raw = full_path.read_bytes()
        # Check trailing newline
        if not raw.endswith(b"\n"):
            whitespace_issues.append(f"{rel_path}: Missing terminating newline")

        lines = full_path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, start=1):
            if line.rstrip(" \t") != line:
                whitespace_issues.append(f"{rel_path}:{idx}: Trailing whitespace detected")

    return whitespace_issues


def main():
    print(f"Verifying documentation from repo root: {REPO_ROOT}")
    total_links, broken_links = check_links()
    whitespace_issues = check_whitespace()

    print(f"\n--- Summary ---")
    print(f"Total internal relative links checked: {total_links}")

    failed = False
    if broken_links:
        print(f"FAILED: Found {len(broken_links)} broken links:")
        for err in broken_links:
            print(f"  - {err}")
        failed = True
    else:
        print(f"PASS: All {total_links} relative links are valid.")

    if whitespace_issues:
        print(f"FAILED: Found {len(whitespace_issues)} whitespace issues:")
        for err in whitespace_issues:
            print(f"  - {err}")
        failed = True
    else:
        print("PASS: No whitespace issues found.")

    if failed:
        sys.exit(1)
    else:
        print("\nALL DOCUMENTATION CHECKS PASSED.")
        sys.exit(0)


if __name__ == "__main__":
    main()
