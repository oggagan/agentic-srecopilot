"""Ingest runbook markdown into pgvector. Run: uv run python -m app.ingest"""
from pathlib import Path

from app.core.pgvector_store import init_schema, upsert_runbook

ROOT = Path(__file__).resolve().parents[2]  # ingest.py -> app -> backend -> root
RUNBOOKS = ROOT / "corpus" / "runbooks"


def main() -> None:
    init_schema()
    files = sorted(RUNBOOKS.glob("*.md"))
    for f in files:
        content = f.read_text()
        first = content.splitlines()[0] if content else f.stem
        title = first.lstrip("# ").strip() or f.stem
        rid = upsert_runbook(title=title, content=content, source=str(f.relative_to(ROOT)))
        print(f"ingested [{rid}] {title}  ({f.name})")
    print(f"done: {len(files)} runbooks")


if __name__ == "__main__":
    main()
