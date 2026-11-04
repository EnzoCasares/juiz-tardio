from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.perfil import consultar_perfil


@tool
def buscar_perfil(busca: str, config: RunnableConfig) -> dict:
    """Consulta renda, objetivo, risco e preferências antes de aconselhar dinheiro.

    busca: pergunta financeira atual, usada na busca semântica das preferências.
    Esta ferramenta apenas lê o cadastro; não salva nem altera dados.
    """
    user_id = config.get("configurable", {}).get("user_id")
    if not user_id:
        return {"orientacao": "Usuário não identificado. Não invente um perfil."}
    try:
        return consultar_perfil(user_id, busca)
    except Exception:
        return {"orientacao": "Não foi possível consultar o perfil agora. Não suponha renda, objetivos ou preferências. Tente novamente mais tarde."}
