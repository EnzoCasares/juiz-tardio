from collections.abc import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.llms import llm_especialista, llm_rapido
from app.prompts import (
    AGENDA_PROMPT_COMPLETO, FAQ_PROMPT_COMPLETO, FINANCEIRO_PROMPT_COMPLETO,
    ORQUESTRADOR_PROMPT_COMPLETO, ROUTER_PROMPT_COMPLETO,
)
from app.tools.agenda import TOOLS_AGENDA
from app.tools.calendario_google import TOOLS_GOOGLE
from app.tools.faq import faq_retriever
from app.tools.financeiro import TOOLS
from app.tools.memoria import TOOLS_MEMORIA
from app.tools.perfil import buscar_perfil


@wrap_tool_call
def serializar_resultado_vazio(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    resultado = handler(request)
    if isinstance(resultado, ToolMessage) and resultado.content == []:
        return resultado.model_copy(update={"content": "[]"})
    return resultado


router_app = create_agent(model=llm_rapido, tools=TOOLS_MEMORIA, system_prompt=ROUTER_PROMPT_COMPLETO, middleware=[serializar_resultado_vazio])
financeiro_app = create_agent(model=llm_especialista, tools=TOOLS + TOOLS_MEMORIA + [buscar_perfil], system_prompt=FINANCEIRO_PROMPT_COMPLETO, middleware=[serializar_resultado_vazio])
agenda_app = create_agent(model=llm_especialista, tools=TOOLS_AGENDA + TOOLS_GOOGLE + TOOLS_MEMORIA, system_prompt=AGENDA_PROMPT_COMPLETO, middleware=[serializar_resultado_vazio])
orquestrador_app = create_agent(
    model=llm_rapido.model_copy(
        update={"model_kwargs": {**llm_rapido.model_kwargs, "tool_choice": "none"}}
    ),
    tools=[],
    system_prompt=ORQUESTRADOR_PROMPT_COMPLETO,
)
faq_app = create_agent(model=llm_rapido, tools=[faq_retriever], system_prompt=FAQ_PROMPT_COMPLETO, middleware=[serializar_resultado_vazio])
