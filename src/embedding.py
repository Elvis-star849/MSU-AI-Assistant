from typing import List, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
import numpy as np
from src.data_loader import load_all_documents

# Sized for yearbook content: 90% of paragraphs (course descriptions, regulation
# clauses) are under ~620 characters, so most fit whole in one chunk.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

# Embedding model used for both chunks and queries (Stages 3-6 must all use the same one)
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# Some models expect an instruction in front of search queries (not in front of the passages)
QUERY_PREFIXES = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
}


def chunk_header(metadata: dict) -> str:
    """Citation header prepended to each chunk, e.g. '[MSU Humanities Yearbook, p. 404]'."""
    page = metadata.get("page")
    return f"[{metadata.get('source', 'Unknown')}, p. {page}]" if page else f"[{metadata.get('source', 'Unknown')}]"


def chunk_documents(documents: List[Any], chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> List[Any]:
    """Split page Documents into chunks, keep their metadata and prefix each with its citation header."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        # Paragraphs first, then lines (each course starts on its own line), then sentences, then words
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = i
        chunk.page_content = f"{chunk_header(chunk.metadata)}\n{chunk.page_content}"
    print(f"[INFO] Split {len(documents)} documents into {len(chunks)} chunks.")
    return chunks


class EmbeddingPipeline:
    def __init__(self, model_name: str = EMBEDDING_MODEL, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP):
        self.model_name = model_name
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.model = SentenceTransformer(model_name)
        self.query_prefix = QUERY_PREFIXES.get(model_name, "")
        print(f"[INFO] Loaded embedding model: {model_name} (dim={self.model.get_embedding_dimension()})")

    def chunk_documents(self, documents: List[Any]) -> List[Any]:
        return chunk_documents(documents, self.chunk_size, self.chunk_overlap)

    def embed_chunks(self, chunks: List[Any]) -> np.ndarray:
        texts = [chunk.page_content for chunk in chunks]
        print(f"[INFO] Generating embeddings for {len(texts)} chunks...")
        # Normalised vectors: dot product == cosine similarity
        embeddings = self.model.encode(texts, show_progress_bar=True, normalize_embeddings=True)
        print(f"[INFO] Embeddings shape: {embeddings.shape}")
        return embeddings.astype("float32")

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a user question (with the model's query prefix, if any) as a (1, dim) float32 array."""
        embedding = self.model.encode([self.query_prefix + query], normalize_embeddings=True)
        return embedding.astype("float32")

# Example usage
if __name__ == "__main__":
    
    docs = load_all_documents()
    emb_pipe = EmbeddingPipeline()
    chunks = emb_pipe.chunk_documents(docs)
    embeddings = emb_pipe.embed_chunks(chunks)
    print("[INFO] Example embedding:", embeddings[0] if len(embeddings) > 0 else None)
