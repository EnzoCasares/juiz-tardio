import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from langchain.tools import tool
from pydantic import Field

from app.operacoes import bloquear, conexao_leitura, gravar_validado, turno_atual


def _moeda_do_texto(texto: str) -> str | None:
    texto = texto.casefold()
    brl = bool(re.search(r"r\$|\b(?:brl|real|reais)\b", texto))
    usd = bool(re.search(r"us\$|\b(?:usd|d[oó]lar(?:es)?|dollars?)\b", texto))
    outra = bool(re.search(
        r"canad|austral|hong kong|[€£¥]|\b(?:eur|euros?|gbp|libras?|ienes?|jpy|pesos?|cad|aud)\b",
        texto,
    ))
    ambiguo = "$" in re.sub(r"(?:r|us)\$", "", texto)
    if outra or ambiguo:
        return None
    if brl and usd:
        return "MULTIPLA"
    return "USD" if usd else "BRL"


def _valor_decimal(valor: float) -> Decimal:
    numero = Decimal(str(valor))
    try:
        valido = numero.is_finite() and numero != 0 and numero == numero.quantize(Decimal("0.01"))
    except InvalidOperation:
        valido = False
    if not valido:
        raise ValueError("O valor deve ser finito, não zero e ter no máximo duas casas decimais.")
    return numero


@tool
def add_transaction(
    valor: float, categoria: str, forma_pagamento: str = "nao informado",
    descricao: str = "", moeda: Literal["BRL", "USD"] = "BRL", source_text: str = "",
) -> dict:
    """Registra gasto/receita realizado, após autorização. Moedas não são convertidas."""
    turno = turno_atual()
    origem = turno.pergunta if turno is not None else source_text
    moeda_texto = _moeda_do_texto(origem)
    if moeda_texto is None:
        return bloquear("Moeda ambígua ou não suportada. Informe BRL/reais ou USD/dólares americanos.")
    if moeda_texto != "MULTIPLA" and moeda != moeda_texto:
        return bloquear("A moeda dos argumentos não corresponde ao relato. Não converta valores.")
    try:
        numero = _valor_decimal(valor)
    except ValueError as erro:
        return bloquear(str(erro))
    argumentos = dict(valor=str(numero), categoria=categoria, forma_pagamento=forma_pagamento,
                      descricao=descricao, moeda=moeda, source_text=origem)

    def executar(conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO transactions (valor, categoria, forma_pagamento, descricao, moeda, source_text) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (numero, categoria, forma_pagamento, descricao, moeda, origem),
            )
            return {"id": cur.fetchone()[0], **argumentos}

    return gravar_validado("add_transaction", argumentos, executar)


@tool
def query_transactions(
    categoria: str | None = None,
    limite: Annotated[int, Field(ge=1, le=100)] = 10,
    moeda: Literal["BRL", "USD"] | None = None,
) -> list[dict]:
    """Consulta transações com id, moeda e texto original; moeda nula significa legado desconhecido."""
    if not 1 <= limite <= 100:
        raise ValueError("O limite deve estar entre 1 e 100.")
    filtros = []
    params = []
    if categoria:
        filtros.append("categoria = %s")
        params.append(categoria)
    if moeda:
        filtros.append("moeda = %s")
        params.append(moeda)
    where = " WHERE " + " AND ".join(filtros) if filtros else ""
    with conexao_leitura() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, valor, categoria, forma_pagamento, descricao, moeda, source_text "
            "FROM transactions" + where + " ORDER BY id DESC LIMIT %s",
            (*params, limite),
        )
        colunas = ["id", "valor", "categoria", "forma_pagamento", "descricao", "moeda", "source_text"]
        return [
            dict(zip(colunas, (linha[0], str(linha[1]), *linha[2:])))
            for linha in cur.fetchall()
        ]


def _saldos(dia: str | None = None, moeda: str | None = None, categoria: str | None = None) -> dict:
    filtros = []
    params = []
    if dia is not None:
        date.fromisoformat(dia)
        filtros.append("DATE(criado_em) = %s")
        params.append(dia)
    if moeda is not None:
        filtros.append("moeda = %s")
        params.append(moeda)
    if categoria is not None:
        filtros.append("categoria = %s")
        params.append(categoria)
    where = " WHERE " + " AND ".join(filtros) if filtros else ""
    with conexao_leitura() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT moeda, SUM(valor), COUNT(*) FROM transactions" + where + " GROUP BY moeda",
            params,
        )
        linhas = cur.fetchall()
    saldos = {sigla: "0.00" for sigla in ([moeda] if moeda else ["BRL", "USD"])}
    desconhecidos = 0
    for sigla, total, quantidade in linhas:
        if sigla is None:
            desconhecidos += quantidade
        else:
            saldos[sigla] = str(total)
    return {"saldos": saldos, "registros_sem_moeda": desconhecidos,
            "observacao": "Moedas separadas, sem conversão. Registros sem moeda não entram nos saldos."}


@tool
def total_balance(moeda: Literal["BRL", "USD"] | None = None, categoria: str | None = None) -> dict:
    """Saldo de todos os registros por moeda e categoria opcional, sem limite de linhas."""
    return _saldos(moeda=moeda, categoria=categoria)


@tool
def daily_balance(
    data: str, moeda: Literal["BRL", "USD"] | None = None, categoria: str | None = None,
) -> dict:
    """Saldo do dia AAAA-MM-DD separado por moeda, sem conversão."""
    return _saldos(dia=data, moeda=moeda, categoria=categoria)


@tool
def update_transaction(
    transaction_id: int, valor: float | None = None, categoria: str | None = None,
    source_text: str = "",
) -> dict:
    """Atualiza transação por id com autorização. Preserva moeda; nunca faz conversão."""
    turno = turno_atual()
    origem = turno.pergunta if turno is not None else source_text
    if valor is None and categoria is None:
        return bloquear("Informe uma alteração de valor ou categoria.")
    try:
        numero = _valor_decimal(valor) if valor is not None else None
    except ValueError as erro:
        return bloquear(str(erro))
    argumentos = dict(transaction_id=transaction_id, valor=str(numero) if numero is not None else None,
                      categoria=categoria, source_text=origem)

    def executar(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT moeda FROM transactions WHERE id = %s FOR UPDATE", (transaction_id,))
            linha = cur.fetchone()
            if linha is None:
                raise ValueError("Transação não encontrada; nada foi alterado.")
            if numero is not None:
                explicita = bool(re.search(r"\$|\b(?:brl|usd|real|reais|d[oó]lar(?:es)?)\b", origem, re.I))
                if linha[0] is None or (explicita and _moeda_do_texto(origem) != linha[0]):
                    raise ValueError("Moeda incompatível ou desconhecida; alteração de valor cancelada.")
            cur.execute(
                "UPDATE transactions SET valor = COALESCE(%s, valor), "
                "categoria = COALESCE(%s, categoria) WHERE id = %s "
                "RETURNING id, valor, categoria, moeda",
                (numero, categoria, transaction_id),
            )
            row = cur.fetchone()
            return {"id": row[0], "valor": str(row[1]), "categoria": row[2], "moeda": row[3]}

    return gravar_validado("update_transaction", argumentos, executar)


TOOLS = [add_transaction, query_transactions, total_balance, daily_balance, update_transaction]
