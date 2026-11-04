import json
import logging
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, MessagesState, StateGraph

from app.guardrail import anonimizar_entrada, guardrail_entrada, guardrail_saida
from app.memory import salvar_mensagem
from app.observabilidade import abrir_turno, fechar_turno, status_do_estado
from app.agents import router_app, financeiro_app, agenda_app, faq_app, orquestrador_app
from app.juiz import no_juiz
from app.operacoes import turno_operacoes

logger = logging.getLogger(__name__)


class Estado(MessagesState):
    agentes_chamados: list[str]
    rota: str
    mapa_pii: dict
    evidencias: list[str]
    validacao_aprovada: bool


def _evidencias_da_saida(saida: dict) -> list[str]:
    mensagens = saida.get("messages", [])
    inicio = max(
        (i for i, mensagem in enumerate(mensagens) if getattr(mensagem, "type", "") == "human"),
        default=-1,
    )
    evidencias = []
    for mensagem in mensagens[inicio + 1 :]:
        if getattr(mensagem, "type", "") == "tool":
            conteudo = getattr(mensagem, "content", "")
            if not isinstance(conteudo, str):
                conteudo = json.dumps(conteudo, ensure_ascii=False, default=str)
            if conteudo.strip():
                nome = getattr(mensagem, "name", None) or "tool"
                evidencias.append(f"[{nome}]\n{conteudo}")
    return evidencias


def _acumular_evidencias(atuais: list[str], novas: list[str]) -> list[str]:
    if not novas:
        return atuais
    texto = "\n\n".join([*atuais, *novas])
    return [texto[-6000:]] if texto else []


def _session_id(config: RunnableConfig) -> str:
    configuravel = (config or {}).get("configurable", {})
    return configuravel.get("thread_id", "")


def _user_id(config: RunnableConfig) -> str:
    configuravel = (config or {}).get("configurable", {})
    return configuravel.get("user_id", "usuario_teste")


def no_guardrail_entrada(estado: Estado, config: RunnableConfig) -> dict:
    ultima = estado["messages"][-1]
    texto_anonimizado, mapa_pii = anonimizar_entrada(ultima.content)
    session_id = _session_id(config)

    if session_id:
        salvar_mensagem(
            session_id,
            "user",
            texto_anonimizado,
            user_id=_user_id(config),
        )

    mensagens = []
    if ultima.id:
        mensagens.append(RemoveMessage(id=ultima.id))

    if guardrail_entrada(texto_anonimizado):
        mensagens.append(
            AIMessage(content="Não posso atender a esse pedido.")
        )
        return {
            "messages": mensagens,
            "mapa_pii": mapa_pii,
            "rota": "bloqueado",
            "evidencias": [],
        }

    mensagens.append(HumanMessage(content=texto_anonimizado))
    return {
        "messages": mensagens,
        "mapa_pii": mapa_pii,
        "rota": "livre",
        "evidencias": [],
    }


def decidir_pos_guardrail_entrada(estado: Estado) -> str:
    return "saida" if estado["rota"] == "bloqueado" else "roteador"


def no_roteador(estado: Estado, config: RunnableConfig) -> dict:
    saida = router_app.invoke(
        {"messages": [SystemMessage(content="Data e hora locais atuais: " + datetime.now().astimezone().isoformat())] + list(estado["messages"])},
        config=config,
    )
    resposta = saida["messages"][-1]
    texto = resposta.content.strip()
    rota = texto.lower().removeprefix("route=").strip()

    if rota in {"financeiro", "agenda", "faq"}:
        evidencias = _acumular_evidencias(
            estado.get("evidencias", []), _evidencias_da_saida(saida)
        )
        return {"rota": rota, "evidencias": evidencias}

    return {
        "messages": [AIMessage(content=texto)],
        "rota": "resposta_direta",
        "agentes_chamados": ["memoria"],
        "evidencias": _acumular_evidencias(
            estado.get("evidencias", []), _evidencias_da_saida(saida)
        ),
    }


def decidir_especialista(estado: Estado) -> str:
    return estado["rota"]


def _executar_especialista(
    estado: Estado,
    config: RunnableConfig,
    nome: str,
    agente,
) -> dict:
    saida = agente.invoke(
        {"messages": [SystemMessage(content="Data e hora locais atuais: " + datetime.now().astimezone().isoformat())] + list(estado["messages"])},
        config=config,
    )
    resposta = saida["messages"][-1]
    chamados = estado.get("agentes_chamados", [])
    return {
        "messages": [AIMessage(content=resposta.content)],
        "agentes_chamados": chamados + [nome],
        "evidencias": _acumular_evidencias(
            estado.get("evidencias", []), _evidencias_da_saida(saida)
        ),
    }


def no_financeiro(estado: Estado, config: RunnableConfig) -> dict:
    return _executar_especialista(estado, config, "financeiro", financeiro_app)


def no_agenda(estado: Estado, config: RunnableConfig) -> dict:
    return _executar_especialista(estado, config, "agenda", agenda_app)


def no_faq(estado: Estado, config: RunnableConfig) -> dict:
    return _executar_especialista(estado, config, "faq", faq_app)


def no_orquestrador(estado: Estado, config: RunnableConfig) -> dict:
    saida = orquestrador_app.invoke(
        {"messages": [SystemMessage(content="Data e hora locais atuais: " + datetime.now().astimezone().isoformat())] + list(estado["messages"])},
        config=config,
    )
    return {"messages": [AIMessage(content=saida["messages"][-1].content)]}


def no_guardrail_saida(estado: Estado, config: RunnableConfig) -> dict:
    ultima = estado["messages"][-1]
    resposta_revisada = guardrail_saida(
        ultima.content,
        estado.get("mapa_pii", {}),
    )
    mensagens = []
    if ultima.id:
        mensagens.append(RemoveMessage(id=ultima.id))
    mensagens.append(AIMessage(content=resposta_revisada))
    return {"messages": mensagens}


def decidir_pos_guardrail_saida(estado: Estado) -> str:
    return "fim" if estado.get("rota") == "bloqueado" else "juiz"


grafo = StateGraph(Estado)
grafo.add_node("guardrail_entrada", no_guardrail_entrada)
grafo.add_node("roteador", no_roteador)
grafo.add_node("financeiro", no_financeiro)
grafo.add_node("agenda", no_agenda)
grafo.add_node("faq", no_faq)
grafo.add_node("orquestrador", no_orquestrador)
grafo.add_node("guardrail_saida", no_guardrail_saida)
grafo.add_node("juiz", no_juiz)

grafo.set_entry_point("guardrail_entrada")
grafo.add_conditional_edges(
    "guardrail_entrada",
    decidir_pos_guardrail_entrada,
    {"roteador": "roteador", "saida": "guardrail_saida"},
)
grafo.add_conditional_edges(
    "roteador",
    decidir_especialista,
    {
        "financeiro": "financeiro",
        "agenda": "agenda",
        "faq": "faq",
        "resposta_direta": "guardrail_saida",
    },
)
grafo.add_edge("financeiro", "orquestrador")
grafo.add_edge("agenda", "orquestrador")
grafo.add_edge("orquestrador", "guardrail_saida")
grafo.add_edge("faq", "juiz")
grafo.add_conditional_edges(
    "guardrail_saida",
    decidir_pos_guardrail_saida,
    {"juiz": "juiz", "fim": END},
)
grafo.add_edge("juiz", END)

fluxo_agentes = grafo.compile(checkpointer=MemorySaver())


def executar_fluxo(
    pergunta: str,
    session_id: str,
    user_id: str = "usuario_teste",
) -> dict:
    config = {
        "configurable": {
            "thread_id": session_id,
            "user_id": user_id,
        }
    }
    pergunta_anonimizada, _ = anonimizar_entrada(pergunta)
    turno_id = abrir_turno()
    status = "erro"
    rota = ""
    try:
        with turno_operacoes(pergunta_anonimizada) as operacoes:
            resultado = fluxo_agentes.invoke(
                {"messages": [("user", pergunta_anonimizada)], "agentes_chamados": [],
                 "validacao_aprovada": False},
                config=config,
            )
            aprovado = operacoes.finalizar(resultado.get("validacao_aprovada", False))
            if operacoes.impedimento or (operacoes.registros and not aprovado):
                motivo = operacoes.impedimento
                if not motivo and "juiz:indisponivel" in resultado.get("agentes_chamados", []):
                    motivo = "A validação está indisponível. Tente novamente em instantes."
                texto = (
                    "Nada foi registrado nem alterado no banco ou no Google neste turno. "
                    + (motivo or "O juiz não aprovou a resposta; a operação foi desfeita.")
                )
                resultado["messages"].append(AIMessage(content=texto))
            elif operacoes.registros and aprovado:
                recibos = []
                for registro in operacoes.registros:
                    if registro["ferramenta"] in {"add_transaction", "update_transaction"}:
                        recibos.append(
                            f"Transação confirmada: id {registro['id']}, "
                            f"{registro['moeda']} {registro['valor']}, "
                            f"categoria {registro['categoria']}."
                        )
                    else:
                        recibos.append(
                            f"Evento local confirmado: id {registro['id']}, "
                            f"{registro['title']}, início {registro['start_time']}."
                        )
                from app.tools.calendario_google import criar_evento_google_aprovado
                for dados in operacoes.google:
                    try:
                        google = criar_evento_google_aprovado(**dados)
                    except Exception as erro:
                        logger.error(
                            "Google falhou apos commit local (%s).", type(erro).__name__,
                        )
                        google = {"status": "error"}
                    if google.get("status") == "ok" and google.get("id"):
                        recibos.append(f"Google Calendar confirmado: id {google['id']}.")
                    else:
                        recibos.append(
                            "O evento local foi salvo, mas o Google Calendar não confirmou a criação. "
                            "Confira o calendário antes de tentar novamente."
                        )
                resultado["messages"].append(AIMessage(content="\n".join(recibos)))
            if hasattr(fluxo_agentes, "update_state"):
                try:
                    mensagens_checkpoint = resultado["messages"]
                    if operacoes.registros or operacoes.impedimento:
                        inicio = max(
                            (i for i, msg in enumerate(mensagens_checkpoint)
                             if isinstance(msg, HumanMessage)), default=-1,
                        )
                        mensagens_checkpoint = [
                            RemoveMessage(id=msg.id)
                            for msg in mensagens_checkpoint[inicio + 1:-1]
                            if isinstance(msg, AIMessage) and msg.id
                        ] + [mensagens_checkpoint[-1]]
                    fluxo_agentes.update_state(
                        config, {"messages": mensagens_checkpoint, "validacao_aprovada": aprovado},
                    )
                except Exception as erro:
                    if not (operacoes.registros and aprovado):
                        raise
                    logger.error("Checkpoint falhou apos commit (%s).", type(erro).__name__)
                    resultado["messages"].append(AIMessage(
                        content=resultado["messages"][-1].content
                        + "\nA operação foi confirmada, mas a memória da conversa falhou.",
                    ))
        status = status_do_estado(resultado)
        rota = resultado.get("rota") or ""
        resposta = resultado["messages"][-1].content
        if session_id:
            try:
                salvar_mensagem(
                    session_id, "assistant", resposta, user_id=user_id,
                )
            except Exception as erro:
                if not (operacoes.registros and aprovado):
                    raise
                logger.error("Historico falhou apos commit (%s).", type(erro).__name__)
                resposta += "\nA operação foi confirmada, mas não foi possível salvar a resposta no histórico."
        return {
            "resposta": resposta,
            "agentes_chamados": resultado.get("agentes_chamados", []),
        }
    finally:
        fechar_turno(turno_id, session_id=session_id, rota=rota, status=status)


