from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.memory import recuperar_historico


@tool
def buscar_historico(busca: str, config: RunnableConfig) -> str:
    """Consulta conversas ANTERIORES do usuário (sessões já encerradas).

    Use SOMENTE quando a resposta depender de algo dito numa conversa passada,
    como preferências, decisões ou planos. NÃO use para gastos, saldos,
    extratos ou eventos, pois esses dados têm ferramentas específicas.

    Args:
        busca: assunto a procurar nos resumos das conversas anteriores.
    """
    configuravel = (config or {}).get("configurable", {})
    user_id = configuravel.get("user_id") or configuravel.get("thread_id")

    if not user_id:
        return "Não foi possível identificar o usuário para buscar o histórico."

    historico = recuperar_historico(user_id, busca=busca, limite=3)
    if not historico:
        return "Nenhuma conversa anterior relevante encontrada."

    linhas = []
    for item in historico:
        data = item["iniciada_em"]
        if hasattr(data, "strftime"):
            data_formatada = data.strftime("%d/%m/%Y")
        else:
            data_formatada = str(data)[:10]
        linhas.append(f"[{data_formatada}] {item['resumo']}")

    return "\n\n".join(linhas)


TOOLS_MEMORIA = [buscar_historico]
