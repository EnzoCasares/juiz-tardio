from uuid import uuid4

from fastapi import APIRouter

from app.memory import encerrar_sessao, iniciar_sessao
from app.schemas import SessionResponse
from app.graph import fluxo_agentes


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/{session_id}/iniciar", response_model=SessionResponse)
def iniciar(session_id: str, user_id: str = "usuario_teste") -> SessionResponse:
    iniciar_sessao(session_id, user_id=user_id)
    return SessionResponse(session_id=session_id, resumo=None)


@router.post("/{session_id}/encerrar", response_model=SessionResponse)
@router.delete("/{session_id}", response_model=SessionResponse)
def encerrar(session_id: str) -> SessionResponse:
    resumo = encerrar_sessao(session_id)
    fluxo_agentes.checkpointer.delete_thread(session_id)
    return SessionResponse(session_id=session_id, resumo=resumo or None)


@router.post("", response_model=SessionResponse)
def criar(user_id: str = "usuario_teste") -> SessionResponse:
    return iniciar(str(uuid4()), user_id=user_id)
