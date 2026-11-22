"""Docs check (M14): relative links and cited results/ paths must exist."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_path = Path(__file__).with_name("check_docs.py")
_spec = importlib.util.spec_from_file_location("check_docs", _path)
assert _spec and _spec.loader
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)


def test_finds_broken_link_and_missing_result(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "a_1234567.json").write_text("{}")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "x.md").write_text("ok")
    md = tmp_path / "README.md"
    md.write_text("[x](docs/x.md) [y](docs/missing.md) [web](https://example.com) "
                  "`results/a_1234567.json` `results/b_7654321.csv` `results/a_*.json` "
                  "[anchor](docs/x.md#sec)\n")  # fmt: skip
    problems = cd.check_file(md, tmp_path)
    assert problems == ["README.md: broken link docs/missing.md",
                        "README.md: missing results/b_7654321.csv"]  # fmt: skip


def test_repository_docs_are_consistent() -> None:
    assert cd.check_repo() == []


def test_links_inside_code_are_examples(tmp_path: Path) -> None:
    """M15: Markdown shown as an example (inline code or fenced block) is not checked."""
    md = tmp_path / "README.md"
    md.write_text("Use `[![x](docs/thumb.png)](https://y)` later.\n\n```\n[z](docs/nope.md)\n```\n")
    assert cd.check_file(md, tmp_path) == []
