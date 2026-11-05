import uuid
from datetime import datetime, timezone

from pymongo import MongoClient
from qdrant_client import models

from app.config import MONGODB_URI
from app.llms import llm_rapido
from app.vectorstore import (
    COLLECTION_MEMORIA,
    gerar_embedding,
    gerar_embedding_documento,
    qdrant,
)


_mongo = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
_cliente = _mongo
db = _mongo["assessor"]
col_sessoes = db["sessoes"]

try:
    col_sessoes.create_index("session_id")
    col_sessoes.create_index("user_id")
    col_sessoes.create_index("iniciada_em")
except Exception as erro:
    print(f"Aviso: índices do MongoDB não criados ({type(erro).__name__}).")

_PROMPT_RESUMO = """\
Você é um assistente que resume conversas de assessoria financeira e agenda.
Gere um resumo conciso em 2-4 frases capturando:
- O que o usuário fez (transações registradas, eventos agendados)
- O que o usuário perguntou
- Informações relevantes mencionadas (valores, datas, categorias)

Responda APENAS com o resumo, sem introdução ou explicação.

Conversa:
{conversa}
"""

_sessoes_ativas: dict[str, str] = {}


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _formatar_conversa(mensagens: list[dict]) -> str:
    return "\n".join(
        f"{mensagem['role']}: {mensagem['content']}"
        for mensagem in mensagens
    )


def _gerar_resumo(mensagens: list[dict]) -> str:
    conversa = _formatar_conversa(mensagens)
    return llm_rapido.invoke(
        _PROMPT_RESUMO.format(conversa=conversa)
    ).content.strip()


def _doc_id_da_sessao(session_id: str) -> str | None:
    doc_id = _sessoes_ativas.get(session_id)
    if doc_id:
        return doc_id

    doc = col_sessoes.find_one(
        {"session_id": session_id, "resumo": {"$in": ["", None]},
         "encerrada_em": {"$in": [None]}},
        {"_id": 1},
        sort=[("iniciada_em", -1)],
    )
    if not doc:
        return None

    _sessoes_ativas[session_id] = doc["_id"]
    return doc["_id"]


def iniciar_sessao(
    session_id: str,
    user_id: str = "usuario_teste",
) -> None:
    if _doc_id_da_sessao(session_id):
        return

    doc_id = str(uuid.uuid4())
    agora = _agora()
    col_sessoes.insert_one(
        {
            "_id": doc_id,
            "session_id": session_id,
            "user_id": user_id,
            "iniciada_em": agora,
            "atualizada_em": agora,
            "resumo": "",
            "mensagens": [],
        }
    )
    _sessoes_ativas[session_id] = doc_id


def salvar_mensagem(
    session_id: str,
    role: str,
    content: str,
    user_id: str = "usuario_teste",
) -> None:
    iniciar_sessao(session_id, user_id=user_id)
    doc_id = _doc_id_da_sessao(session_id)
    col_sessoes.update_one(
        {"_id": doc_id},
        {
            "$push": {"mensagens": {"role": role, "content": content}},
            "$set": {"atualizada_em": _agora()},
        },
    )


def encerrar_sessao(session_id: str) -> str:
    doc_id = _doc_id_da_sessao(session_id)
    if not doc_id:
        return ""

    doc = col_sessoes.find_one({"_id": doc_id})
    if not doc or not doc.get("mensagens"):
        if doc:
            col_sessoes.update_one(
                {"_id": doc_id}, {"$set": {"encerrada_em": _agora()}},
            )
        _sessoes_ativas.pop(session_id, None)
        return ""

    resumo = _gerar_resumo(doc["mensagens"])
    user_id = doc.get("user_id", "usuario_teste")
    vetor = gerar_embedding_documento(resumo)
    qdrant.upsert(
        collection_name=COLLECTION_MEMORIA,
        wait=True,
        points=[
            models.PointStruct(
                id=str(doc_id),
                vector=vetor,
                payload={
                    "user_id": user_id,
                    "session_id": session_id,
                    "resumo": resumo,
                    "iniciada_em": doc["iniciada_em"].isoformat(),
                },
            )
        ],
    )

    col_sessoes.update_one(
        {"_id": doc_id},
        {"$set": {"resumo": resumo, "atualizada_em": _agora(),
                  "encerrada_em": _agora()}},
    )
    _sessoes_ativas.pop(session_id, None)
    return resumo


def recuperar_historico(
    user_id: str,
    busca: str = "",
    limite: int = 3,
) -> list[dict]:
    if busca:
        vetor = gerar_embedding(busca)
        resultados = qdrant.query_points(
            collection_name=COLLECTION_MEMORIA,
            query=vetor,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="user_id",
                        match=models.MatchValue(value=user_id),
                    )
                ]
            ),
            limit=limite,
        )
        if resultados.points:
            return [
                {
                    "doc_id": ponto.id,
                    "iniciada_em": ponto.payload.get("iniciada_em", ""),
                    "resumo": ponto.payload["resumo"],
                }
                for ponto in resultados.points
            ]

    filtro = {"user_id": user_id, "resumo": {"$nin": ["", None]}}
    docs = (
        col_sessoes.find(filtro, {"resumo": 1, "iniciada_em": 1})
        .sort("iniciada_em", -1)
        .limit(limite)
    )
    return [
        {
            "doc_id": doc["_id"],
            "iniciada_em": doc["iniciada_em"],
            "resumo": doc["resumo"],
        }
        for doc in docs
    ]


def recuperar_mensagens(doc_id: str) -> list[dict]:
    doc = col_sessoes.find_one({"_id": doc_id}, {"mensagens": 1})
    return doc["mensagens"] if doc else []
