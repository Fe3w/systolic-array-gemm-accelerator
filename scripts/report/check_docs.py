#!/usr/bin/env python3
"""Check the Markdown docs (M14): every relative link points at an existing file,
and every `results/...` path cited in backticks exists (globs must match at least
one file). Checked: README.md, docs/*.md, docs/spec/*.md, scripts/**/README.md,
results/**/*.md. History files (DECISIONS) cite results at the time they were written and
are checked too.

Usage (repo root): python3 scripts/report/check_docs.py   (exit 1 on problems)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\]\(([^)\s]+)\)")
RESULT = re.compile(r"`(results/[^`\s]+)`")


def doc_files(repo: Path) -> list[Path]:
    files = [repo / "README.md"] + sorted((repo / "docs").glob("*.md"))
    files += sorted((repo / "docs" / "spec").glob("*.md"))
    files += sorted((repo / "scripts").rglob("README.md"))
    files += sorted((repo / "results").rglob("*.md"))
    return [f for f in files if f.exists()]


def expand_braces(path: str) -> list[str]:
    """Shell-style {a,b} expansion (one level per pass), as the docs sometimes cite."""
    m = re.search(r"\{([^{}]*)\}", path)
    if not m:
        return [path]
    return [p for alt in m.group(1).split(",")
            for p in expand_braces(path[: m.start()] + alt + path[m.end():])]  # fmt: skip


def check_file(md: Path, repo: Path) -> list[str]:
    text = md.read_text()
    rel = md.relative_to(repo)
    problems = []
    # Links inside fenced blocks or inline code are examples, not links.
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    prose = re.sub(r"`[^`\n]*`", "", prose)
    for target in LINK.findall(prose):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue  # web links and same-page anchors
        path = target.split("#")[0]
        if path and not (md.parent / path).exists():
            problems.append(f"{rel}: broken link {path}")
    for cited in RESULT.findall(text):
        cited = cited.rstrip(".,;:)")
        if "<" in cited:
            continue  # templates such as results/perf/<sha>.csv
        ok = all(any(repo.glob(p)) if any(ch in p for ch in "*?[") else (repo / p).exists()
                 for p in expand_braces(cited))  # fmt: skip
        if not ok:
            problems.append(f"{rel}: missing {cited}")
    return problems


def check_repo(repo: Path = REPO) -> list[str]:
    return [p for f in doc_files(repo) for p in check_file(f, repo)]


def main() -> int:
    problems = check_repo()
    for p in problems:
        print(p)
    print(f"check_docs: {len(doc_files(REPO))} files, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
