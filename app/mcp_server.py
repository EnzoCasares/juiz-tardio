import sys
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from app.tools.agenda import add_event as _add_event, query_events as _query_events

from app.tools.financeiro import (
    add_transaction as _add_transaction,
    daily_balance as _daily_balance,
    query_transactions as _query_transactions,
    total_balance as _total_balance,
    update_transaction as _update_transaction,
)

mcp = MCPServer(
    name="assessor-financeiro",
    version="1.0.0",
    instructions="Ferramentas financeiras e de agenda local do Assessor.AI.",
)

coletor = mcp

LEITURA = ToolAnnotations(readOnlyHint=True)
ESCRITA = ToolAnnotations(readOnlyHint=False, destructiveHint=False)


@mcp.tool(
    name="query_transactions",
    title="Consultar transações",
    description="Lista as transações mais recentes, com filtro opcional por categoria.",
    annotations=LEITURA,
)
def query_transactions(
    categoria: Annotated[
        Optional[str],
        Field(description="Categoria exata pela qual as transações serão filtradas."),
    ] = None,
    limite: Annotated[
        int,
        Field(description="Quantidade máxima de transações retornadas.", ge=1, le=100),
    ] = 10,
    moeda: Literal["BRL", "USD"] | None = None,
) -> list[dict[str, Any]]:
    return _query_transactions.invoke({"categoria": categoria, "limite": limite, "moeda": moeda})


@mcp.tool(
    name="total_balance",
    title="Saldo total",
    description="Saldo por moeda. Nunca soma BRL com USD.",
    annotations=LEITURA,
)
def total_balance(moeda: Literal["BRL", "USD"] | None = None, categoria: str | None = None) -> dict:
    return _total_balance.invoke({"moeda": moeda, "categoria": categoria})


@mcp.tool(
    name="daily_balance",
    title="Saldo diário",
    description="Saldo das transações registradas em um dia específico.",
    annotations=LEITURA,
)
def daily_balance(
    data: Annotated[
        str,
        Field(description="Data no formato AAAA-MM-DD.", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ],
    moeda: Literal["BRL", "USD"] | None = None,
    categoria: str | None = None,
) -> dict:
    return _daily_balance.invoke({"data": data, "moeda": moeda, "categoria": categoria})


@mcp.tool(
    name="add_transaction",
    title="Registrar transação",
    description="Registra uma transação na tabela transactions.",
    annotations=ESCRITA,
)
def add_transaction(
    valor: Annotated[float, Field(description="Valor da transação.")],
    categoria: Annotated[str, Field(description="Categoria da transação.", min_length=1)],
    forma_pagamento: Annotated[
        str,
        Field(description="Forma de pagamento da transação.", min_length=1),
    ],
    descricao: Annotated[str, Field(description="Descrição opcional da transação.")] = "",
    moeda: Literal["BRL", "USD"] = "BRL",
    source_text: Annotated[str, Field(description="Pedido original; obrigatório para autorizar a gravação.")] = "",
) -> dict:
    return _add_transaction.invoke(
        {
            "valor": valor,
            "categoria": categoria,
            "forma_pagamento": forma_pagamento,
            "descricao": descricao,
            "moeda": moeda,
            "source_text": source_text,
        }
    )


@mcp.tool(
    name="update_transaction",
    title="Atualizar transação",
    description="Atualiza o valor e/ou a categoria de uma transação pelo id.",
    annotations=ESCRITA,
)
def update_transaction(
    transaction_id: Annotated[int, Field(description="Id da transação.", ge=1)],
    valor: Annotated[
        Optional[float],
        Field(description="Novo valor da transação."),
    ] = None,
    categoria: Annotated[
        Optional[str],
        Field(description="Nova categoria da transação."),
    ] = None,
    source_text: Annotated[str, Field(description="Pedido original da alteração.")] = "",
) -> dict:
    return _update_transaction.invoke(
        {
            "transaction_id": transaction_id,
            "valor": valor,
            "categoria": categoria,
            "source_text": source_text,
        }
    )


@mcp.tool(
    name="add_event",
    title="Registrar compromisso",
    description="Grava um compromisso na agenda local do Postgres; não altera o Google Calendar.",
    annotations=ESCRITA,
)
def add_event(
    title: Annotated[str, Field(description="Título do compromisso.", min_length=1)],
    source_text: Annotated[str, Field(description="Texto original do usuário.")],
    start_time: Annotated[str, Field(description="Início em ISO 8601 com fuso, por exemplo 2030-01-15T15:00:00-03:00.")],
    end_time: Annotated[Optional[str], Field(description="Fim em ISO 8601 com fuso.")] = None,
    location: Annotated[Optional[str], Field(description="Local do compromisso.")] = None,
    notes: Annotated[Optional[str], Field(description="Observações adicionais.")] = None,
) -> dict:
    return _add_event.invoke({
        "title": title, "source_text": source_text, "start_time": start_time,
        "end_time": end_time, "location": location, "notes": notes,
    })


@mcp.tool(
    name="query_events",
    title="Consultar compromissos",
    description="Consulta a agenda local por texto e datas em America/Sao_Paulo.",
    annotations=LEITURA,
)
def query_events(
    text: Annotated[Optional[str], Field(description="Busca em título, local, notas e texto original.")] = None,
    date_local: Annotated[Optional[str], Field(description="Dia YYYY-MM-DD em America/Sao_Paulo.")] = None,
    date_from_local: Annotated[Optional[str], Field(description="Data inicial inclusiva YYYY-MM-DD.")] = None,
    date_to_local: Annotated[Optional[str], Field(description="Data final inclusiva YYYY-MM-DD.")] = None,
    limit: Annotated[int, Field(description="Máximo de eventos retornados (1 a 200).", ge=1, le=200)] = 20,
) -> dict:
    return _query_events.invoke({
        "text": text, "date_local": date_local,
        "date_from_local": date_from_local, "date_to_local": date_to_local,
        "limit": limit,
    })


if __name__ == "__main__":
    from app.config import DATABASE_URL

    if not DATABASE_URL:
        print(
            "[assessor-financeiro] DATABASE_URL ausente no .env",
            file=sys.stderr,
        )

    mcp.run(transport="stdio")
