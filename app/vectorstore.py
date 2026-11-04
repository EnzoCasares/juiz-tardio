import warnings

from fastembed import TextEmbedding
from qdrant_client import QdrantClient

from app.config import QDRANT_API_KEY, QDRANT_URL


with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Api key is used with an insecure connection.")
    qdrant = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        check_compatibility=False,
    )

COLLECTION_MEMORIA = "memoria_resumos"
COLLECTION_FAQ = "faq_chunks"
EMBEDDING_DIM = 768
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5-Q"

_embeddings: TextEmbedding | None = None


def _obter_modelo_embeddings() -> TextEmbedding:
    global _embeddings
    if _embeddings is None:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="The model 'nomic-ai/nomic-embed-text-v1.5-Q' has been updated.*",
            )
            _embeddings = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _embeddings


def gerar_embedding(texto: str) -> list[float]:
    vetor = next(_obter_modelo_embeddings().query_embed(texto))
    return vetor.tolist()


def gerar_embedding_documento(texto: str) -> list[float]:
    vetor = next(_obter_modelo_embeddings().passage_embed([texto]))
    return vetor.tolist()


def gerar_embeddings_batch(textos: list[str]) -> list[list[float]]:
    return [
        vetor.tolist()
        for vetor in _obter_modelo_embeddings().passage_embed(textos)
    ]
