from qdrant_client import models

from app.vectorstore import (
    COLLECTION_FAQ,
    COLLECTION_MEMORIA,
    EMBEDDING_DIM,
    qdrant,
)


def criar_collections() -> None:
    existentes = {
        collection.name for collection in qdrant.get_collections().collections
    }

    for nome in (COLLECTION_MEMORIA, COLLECTION_FAQ):
        if nome not in existentes:
            qdrant.create_collection(
                collection_name=nome,
                vectors_config=models.VectorParams(
                    size=EMBEDDING_DIM,
                    distance=models.Distance.COSINE,
                ),
            )

    qdrant.create_payload_index(
        collection_name=COLLECTION_MEMORIA,
        field_name="user_id",
        field_schema=models.KeywordIndexParams(
            type="keyword",
            is_tenant=True,
        ),
        wait=True,
    )

    for nome in (COLLECTION_MEMORIA, COLLECTION_FAQ):
        info = qdrant.get_collection(nome)
        print(
            f"[qdrant] {nome}: status={info.status.value}, "
            f"pontos={info.points_count}, "
            f"dimensão={info.config.params.vectors.size}, "
            f"distância={info.config.params.vectors.distance.value}"
        )


if __name__ == "__main__":
    criar_collections()
