import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.schemas import ChatRequest, ChatResponse
from app.graph import executar_fluxo

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse)
def conversar(requisicao: ChatRequest):
    try:
        resultado = executar_fluxo(
            requisicao.pergunta,
            requisicao.session_id,
            requisicao.user_id,
        )
    except Exception as erro:
        logger.error("Falha no chat (%s).", type(erro).__name__)
        detalhe_erro = str(erro)
        if "429" in detalhe_erro or "rate_limit" in detalhe_erro.lower():
            resposta = (
                "O modelo de IA atingiu o limite de requisições por minuto "
                "(plano gratuito da Groq). Aguarde alguns segundos e tente de novo."
            )
        else:
            resposta = "Não consegui processar sua mensagem agora. Tente novamente em instantes."
        resposta += " Nenhuma nova operação foi confirmada neste pedido."
        return JSONResponse(
            status_code=503,
            content={
                "resposta": resposta,
                "agentes_chamados": [],
                "status": 503,
                "detail": resposta,
                "rota": "/chat",
            },
        )

    return ChatResponse(
        resposta=resultado["resposta"],
        agentes_chamados=resultado["agentes_chamados"],
    )
