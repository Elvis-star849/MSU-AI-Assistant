"""
Embedding of new passages and the embedding cache.

The cache (knowledge_base/embeddings/<model key>/batch-*.npz) is keyed by the SHA-256 of the exact indexed text
(heading_store.index_text). The model key covers model name, revision and recipe, so vectors from a different model
can never be mixed in. Each batch file is written atomically; an interrupted run keeps the finished batches and
resumes. Version builds read vectors from here and never re-embed.
"""
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Sequence

import numpy as np

from src.kb.errors import IntegrityError
from src.kb import fsutil
from src.kb.fsutil import atomic_write_bytes, canonical_json


class Embedder(Protocol):
    model_name: str
    revision: str
    dim: int

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Normalised float32 vectors, one row per text."""


class SentenceTransformerEmbedder:
    """The accepted passage embedder (same call as HeadingAwareStore.build_from_records). Loaded from the local
    Hugging Face cache; refuses to run if the cached revision is not the one that produced the frozen vectors."""

    def __init__(self, model_name: str, expected_revision: str, batch_size: int = 32):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from huggingface_hub import try_to_load_from_cache
        from sentence_transformers import SentenceTransformer

        config_path = try_to_load_from_cache(model_name, "config.json")
        revision = Path(config_path).parent.name if isinstance(config_path, str) else None
        if revision != expected_revision:
            raise IntegrityError(f"{model_name}: cached revision {revision!r}, expected {expected_revision!r}")
        self.model_name, self.revision, self.batch_size = model_name, revision, batch_size
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_embedding_dimension()

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return self.model.encode(list(texts), batch_size=self.batch_size, show_progress_bar=False,
                                 normalize_embeddings=True).astype("float32")


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    def __init__(self, root: Path, model_name: str, revision: str, recipe: str):
        self.meta = {"model": model_name, "revision": revision, "recipe": recipe}
        self.key = hashlib.sha256(canonical_json(self.meta)).hexdigest()[:16]
        self.dir = Path(root) / self.key
        self._index: Optional[Dict[str, np.ndarray]] = None

    def _load_index(self) -> Dict[str, np.ndarray]:
        if self._index is None:
            self._index = {}
            if self.dir.is_dir():
                meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
                if meta != self.meta:
                    raise IntegrityError(f"embedding cache {self.dir} belongs to {meta}, not {self.meta}")
                for f in sorted(self.dir.glob("batch-*.npz")):
                    with np.load(f, allow_pickle=False) as z:
                        hashes, vectors = z["hashes"], z["vectors"]
                    if len(hashes) != len(vectors) or not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3):
                        raise IntegrityError(f"corrupt embedding cache batch {f.name}")
                    for h, v in zip(hashes.tolist(), vectors):
                        self._index[h] = v
        return self._index

    def get(self, texts: Sequence[str]) -> Dict[str, np.ndarray]:
        index = self._load_index()
        return {h: index[h] for h in (text_sha(t) for t in texts) if h in index}

    def missing(self, texts: Sequence[str]) -> List[str]:
        index = self._load_index()
        seen, out = set(), []
        for t in texts:
            h = text_sha(t)
            if h not in index and h not in seen:
                seen.add(h)
                out.append(t)
        return out

    def put(self, texts: Sequence[str], vectors: np.ndarray) -> None:
        vectors = np.ascontiguousarray(vectors, dtype="float32")
        if vectors.shape[0] != len(texts) or not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3):
            raise ValueError("vectors must be normalised and match the texts")
        self.dir.mkdir(parents=True, exist_ok=True)
        meta_path = self.dir / "meta.json"
        if not meta_path.is_file():
            atomic_write_bytes(meta_path, canonical_json(self.meta))
        hashes = np.array([text_sha(t) for t in texts])
        name = "batch-" + hashlib.sha256("".join(hashes.tolist()).encode()).hexdigest()[:20] + ".npz"
        buf = io.BytesIO()
        np.savez(buf, hashes=hashes, vectors=vectors)
        atomic_write_bytes(self.dir / name, buf.getvalue())
        index = self._load_index()
        for h, v in zip(hashes.tolist(), vectors):
            index[h] = v

    def ensure(self, texts: Sequence[str], embedder_factory: Callable[[], Embedder], batch_size: int = 64,
               progress: Optional[Callable[[int, int], None]] = None) -> int:
        """Embed and cache every text not cached yet, one atomic batch at a time. Returns how many were embedded."""
        todo = self.missing(texts)
        if not todo:
            return 0
        embedder = embedder_factory()
        if (embedder.model_name, embedder.revision) != (self.meta["model"], self.meta["revision"]):
            raise IntegrityError(f"embedder {embedder.model_name}@{embedder.revision} does not match the cache "
                                 f"{self.meta['model']}@{self.meta['revision']}")
        for start in range(0, len(todo), batch_size):
            batch = todo[start:start + batch_size]
            self.put(batch, embedder.encode(batch))
            fsutil.crash_point("embedding_batch_written")
            if progress:
                progress(min(start + batch_size, len(todo)), len(todo))
        return len(todo)

    def vectors_for(self, texts: Sequence[str]) -> np.ndarray:
        found = self.get(texts)
        missing = [t for t in texts if text_sha(t) not in found]
        if missing:
            raise IntegrityError(f"{len(missing)} passages have no cached embedding (stage the document first)")
        return np.stack([found[text_sha(t)] for t in texts]).astype("float32")
