from uuid import NAMESPACE_URL, uuid5

from qdrant_client import models

from app.memory import db
from app.vectorstore import (
    EMBEDDING_DIM, gerar_embedding, gerar_embedding_documento, qdrant,
)

COLLECTION_PERFIL = "perfil_preferencias"
col_perfis = db["perfis"]


def salvar_perfil(dados: dict) -> dict:
    vetor = gerar_embedding_documento(dados["preferencias"])
    if not qdrant.collection_exists(COLLECTION_PERFIL):
        qdrant.create_collection(
            collection_name=COLLECTION_PERFIL,
            vectors_config=models.VectorParams(
                size=EMBEDDING_DIM, distance=models.Distance.COSINE,
            ),
        )
        qdrant.create_payload_index(
            collection_name=COLLECTION_PERFIL,
            field_name="user_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )

    user_id = dados["user_id"]
    qdrant.upsert(
        collection_name=COLLECTION_PERFIL,
        points=[models.PointStruct(
            id=str(uuid5(NAMESPACE_URL, "assessor/perfil/" + user_id)),
            vector=vetor,
            payload={"user_id": user_id, "preferencias": dados["preferencias"]},
        )],
        wait=True,
    )
    estruturado = {chave: valor for chave, valor in dados.items() if chave != "preferencias"}
    col_perfis.replace_one({"_id": user_id}, {"_id": user_id, **estruturado}, upsert=True)
    return dados


def consultar_perfil(user_id: str, busca: str) -> dict:
    perfil = col_perfis.find_one({"_id": user_id}, {"_id": 0})
    if perfil is None:
        return {"orientacao": "Perfil não cadastrado. Use a tela Perfil (perfil.html) para cadastrar."}

    pontos = qdrant.query_points(
        collection_name=COLLECTION_PERFIL,
        query=gerar_embedding(busca),
        query_filter=models.Filter(must=[models.FieldCondition(
            key="user_id", match=models.MatchValue(value=user_id),
        )]),
        limit=1,
        with_payload=True,
    ).points
    if not pontos:
        raise RuntimeError("Preferências indisponíveis; salve novamente pela tela Perfil.")
    return {**perfil, "preferencias": pontos[0].payload["preferencias"]}
