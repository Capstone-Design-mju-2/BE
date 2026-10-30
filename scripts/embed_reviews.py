"""Embed every review with BGE-M3 into .local/embeddings, chunk by chunk so a stopped run resumes (ADR-101).

    caffeinate -i uv run --package search-mcp --extra embed python scripts/embed_reviews.py
    uv run --package search-mcp --extra embed python scripts/embed_reviews.py --limit 1000

The model runs in float32 and vectors are kept in float32, so the index can be compared at 16-bit and full precision.
"""

import argparse
import csv
import io
import subprocess
import sys
import time
from pathlib import Path

CHUNK = 10_000
BATCH = 32
OUT = Path(".local/embeddings/bge-m3")


def chunks(total: int, size: int) -> list[range]:
    """
    >>> chunks(25, 10)
    [range(0, 10), range(10, 20), range(20, 25)]
    """
    return [range(start, min(start + size, total)) for start in range(0, total, size)]


def reviews(limit: int | None) -> list[tuple[int, str]]:
    query = "COPY (SELECT id, content FROM reviews ORDER BY id{}) TO STDOUT WITH (FORMAT csv)".format(
        f" LIMIT {limit}" if limit else "")
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "catalog-db", "psql", "-U", "catalog", "-d", "catalog", "-c", query],
        capture_output=True, text=True, check=True,
    ).stdout
    return [(int(review_id), content) for review_id, content in csv.reader(io.StringIO(out))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="embed only the first N reviews, into a separate folder")
    args = parser.parse_args()

    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    rows = reviews(args.limit)
    out = OUT.with_name(f"{OUT.name}-limit{args.limit}") if args.limit else OUT
    out.mkdir(parents=True, exist_ok=True)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer("BAAI/bge-m3", device=device)
    print(f"{len(rows)} reviews on {device}", flush=True)

    started = time.perf_counter()
    embedded = 0
    for part in chunks(len(rows), CHUNK):
        ids = np.array([rows[i][0] for i in part], dtype=np.int64)
        path = out / f"{part.start:07d}.npz"
        if path.exists():
            # Chunks are cut by position, so a changed table would pair old vectors with other reviews.
            if not np.array_equal(np.load(path)["ids"], ids):
                print(f"{path} holds other reviews: the table changed since it was written", file=sys.stderr)
                return 1
            continue
        vectors = model.encode([rows[i][1] for i in part], batch_size=BATCH, normalize_embeddings=True,
                               convert_to_numpy=True).astype(np.float32)
        # Written under another name first so a killed run never leaves a half chunk that looks finished.
        partial = path.with_suffix(".partial.npz")
        np.savez(partial, ids=ids, vectors=vectors)
        partial.rename(path)
        if device == "mps":
            # The MPS allocator kept a block for each new batch shape: 7.5 GB of GPU memory after 600k reviews, enough
            # to push the machine into swap and halve the speed.
            torch.mps.empty_cache()
        embedded += len(part)
        elapsed = time.perf_counter() - started
        print(f"{part.stop}/{len(rows)} reviews, {elapsed / 60:.1f} min, {embedded / elapsed:.1f} reviews/s",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
