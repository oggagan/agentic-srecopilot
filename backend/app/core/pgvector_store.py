"""pgvector backed runbook store with hybrid (dense + keyword) retrieval.

Dense retrieval uses pgvector cosine distance; sparse uses Postgres full text search.
Results are fused with Reciprocal Rank Fusion (RRF), the same approach as the veridoc app.
"""
import psycopg
from pgvector.psycopg import register_vector

from app.config import settings
from app.core.embeddings import embed_documents, embed_query

_RRF_K = 60


def _conn():
    conn = psycopg.connect(settings.database_url)
    register_vector(conn)
    return conn


def init_schema() -> None:
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS runbooks (
                 id serial PRIMARY KEY,
                 title text NOT NULL,
                 service text,
                 content text NOT NULL,
                 source text,
                 created_at timestamptz DEFAULT now())"""
        )
        conn.execute(
            f"""CREATE TABLE IF NOT EXISTS runbook_chunks (
                 id serial PRIMARY KEY,
                 runbook_id int REFERENCES runbooks(id) ON DELETE CASCADE,
                 chunk_index int,
                 text text NOT NULL,
                 embedding vector({settings.embedding_dim}),
                 tsv tsvector)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS rc_embed_idx ON runbook_chunks USING hnsw (embedding vector_cosine_ops)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS rc_tsv_idx ON runbook_chunks USING gin (tsv)")
        conn.commit()


def chunk_text(text: str, target: int = 600, overlap: int = 80) -> list[str]:
    """Pack paragraphs into ~target sized chunks with a little overlap."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= target:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = (buf[-overlap:] + "\n\n" + p) if buf else p
    if buf:
        chunks.append(buf)
    return chunks or [text]


def upsert_runbook(title: str, content: str, service: str | None = None, source: str | None = None) -> int:
    chunks = chunk_text(content)
    embs = embed_documents(chunks)
    with _conn() as conn:
        conn.execute("DELETE FROM runbooks WHERE title = %s", (title,))
        rid = conn.execute(
            "INSERT INTO runbooks (title, service, content, source) VALUES (%s, %s, %s, %s) RETURNING id",
            (title, service, content, source),
        ).fetchone()[0]
        for i, (ch, emb) in enumerate(zip(chunks, embs)):
            conn.execute(
                "INSERT INTO runbook_chunks (runbook_id, chunk_index, text, embedding, tsv) "
                "VALUES (%s, %s, %s, %s, to_tsvector('english', %s))",
                (rid, i, ch, emb, ch),
            )
        conn.commit()
    return rid


def hybrid_search(query: str, k: int | None = None) -> list[dict]:
    k = k or settings.rag_top_k
    qv = embed_query(query)
    with _conn() as conn:
        dense = conn.execute(
            """SELECT rc.id, r.title, r.service, rc.text
               FROM runbook_chunks rc JOIN runbooks r ON r.id = rc.runbook_id
               ORDER BY rc.embedding <=> %s LIMIT %s""",
            (qv, k * 2),
        ).fetchall()
        sparse = conn.execute(
            """SELECT rc.id, r.title, r.service, rc.text
               FROM runbook_chunks rc JOIN runbooks r ON r.id = rc.runbook_id
               WHERE rc.tsv @@ websearch_to_tsquery('english', %s)
               ORDER BY ts_rank(rc.tsv, websearch_to_tsquery('english', %s)) DESC LIMIT %s""",
            (query, query, k * 2),
        ).fetchall()

    scores: dict[int, float] = {}
    rows: dict[int, tuple] = {}
    for ranked in (dense, sparse):
        for rank, (cid, title, service, text) in enumerate(ranked):
            rows[cid] = (title, service, text)
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
    top = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
    return [
        {"chunk_id": cid, "title": rows[cid][0], "service": rows[cid][1], "text": rows[cid][2], "score": round(s, 5)}
        for cid, s in top
    ]
