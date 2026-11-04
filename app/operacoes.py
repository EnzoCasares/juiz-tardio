import json
import logging
import re
import unicodedata
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from _thread import RLock

from psycopg2.extensions import connection

from app.juiz import autorizar_operacao, no_juiz
from app.tools.db import get_conn

logger = logging.getLogger(__name__)


@dataclass
class OperacoesTurno:
    pergunta: str
    conn: connection | None = None
    registros: list[dict] = field(default_factory=list)
    google: list[dict] = field(default_factory=list)
    impedimento: str = ""
    cache: dict[str, dict] = field(default_factory=dict)
    lock: RLock = field(default_factory=RLock)
    confirmado: bool = False

    def conectar(self) -> connection:
        if self.conn is None:
            self.conn = get_conn()
            with self.conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '2s'")
                cur.execute("SET LOCAL statement_timeout = '10s'")
                cur.execute("SET LOCAL idle_in_transaction_session_timeout = '120s'")
        return self.conn

    def finalizar(self, aprovado: bool) -> bool:
        permitido = aprovado and not self.impedimento
        if self.conn is not None:
            if permitido:
                self.conn.commit()
                self.confirmado = True
            else:
                self.conn.rollback()
        return permitido


_turno: ContextVar[OperacoesTurno | None] = ContextVar("operacoes_turno", default=None)


def turno_atual() -> OperacoesTurno | None:
    return _turno.get()


@contextmanager
def turno_operacoes(pergunta: str) -> Generator[OperacoesTurno]:
    turno = OperacoesTurno(pergunta=pergunta)
    token = _turno.set(turno)
    try:
        yield turno
    finally:
        try:
            if turno.conn is not None:
                try:
                    try:
                        turno.conn.rollback()
                    finally:
                        turno.conn.close()
                except Exception as erro:
                    if not turno.confirmado:
                        raise
                    logger.error("Conexao falhou ao encerrar apos commit (%s).", type(erro).__name__)
        finally:
            _turno.reset(token)


@contextmanager
def conexao_leitura() -> Generator[connection]:
    turno = turno_atual()
    if turno is not None:
        with turno.lock:
            yield turno.conectar()
    else:
        conn = get_conn()
        try:
            yield conn
        finally:
            conn.close()


def bloquear(motivo: str) -> dict:
    turno = turno_atual()
    if turno is not None:
        turno.impedimento = motivo
    logger.warning("Operacao bloqueada: %s", motivo)
    return {"status": "bloqueado", "message": motivo}


def impedimento_intencao(pergunta: str, nome: str) -> str:
    texto = "".join(
        letra for letra in unicodedata.normalize("NFKD", pergunta.casefold())
        if not unicodedata.combining(letra)
    )
    if not texto.strip():
        return "Falta a solicitação original para autorizar a operação."
    if re.search(r"\b(?:e se|se eu|caso eu|por exemplo|suponha|hipoteticamente)\b", texto):
        return "Hipóteses e exemplos não são lançamentos realizados."
    if re.search(
        r"\bnao\s+(?:quero\s+)?(?:registre|registrar|lance|lancar|anote|anotar|salve|salvar|"
        r"crie|criar|agende|agendar|marque|marcar|altere|alterar|gastei|paguei|recebi)\b",
        texto,
    ):
        return "A mensagem não autoriza esta gravação."
    if nome in {"add_transaction", "update_transaction"} and re.search(
        r"\b(?:(?:quero|vou|pretendo|planejo|deveria|poderia)\s+"
        r"(?:gastar|comprar|pagar|receber|ganhar)|gastaria|pagaria|receberia)\b",
        texto,
    ):
        return "Planos futuros não são gastos ou receitas realizados."
    pedido_explicito = re.search(
        r"\b(?:registre|registra|lance|anote|salve|adicione|altere|atualize|corrija|"
        r"agende|marque|crie|(?:pode|poderia)\s+(?:registrar|anotar|salvar|agendar|criar))\b",
        texto,
    )
    if "?" in texto and not pedido_explicito:
        return "Uma pergunta não autoriza uma nova gravação."
    return ""


def gravar_validado(
    nome: str, argumentos: dict, executar: Callable[[connection], dict],
) -> dict:
    turno = turno_atual()
    if turno is None:
        with turno_operacoes(argumentos.get("source_text", "")) as novo:
            resultado = gravar_validado(nome, argumentos, executar)
            if resultado.get("status") != "pendente":
                return resultado
            estado = _validar_resultado_direto(novo, resultado)
            if not novo.finalizar(estado.get("validacao_aprovada", False)):
                if "juiz:indisponivel" in estado.get("agentes_chamados", []):
                    return bloquear("A validação está indisponível; nada foi registrado nem alterado.")
                return bloquear("Operação não aprovada pelo juiz; nada foi registrado.")
            return {**resultado, "status": "ok"}
    with turno.lock:
        if turno.impedimento:
            return bloquear(turno.impedimento)
        motivo = impedimento_intencao(turno.pergunta, nome)
        if motivo:
            return bloquear(motivo)
        chave = json.dumps([nome, argumentos], sort_keys=True, default=str)
        if chave in turno.cache:
            return turno.cache[chave]
        try:
            veredito = autorizar_operacao(turno.pergunta, nome, argumentos)
        except Exception as erro:
            logger.error("Autorizacao indisponivel (%s).", type(erro).__name__)
            return bloquear("Validação indisponível; nada foi registrado.")
        if not veredito.aprovado:
            return bloquear("Pedido ou argumentos não autorizam esta operação. Peça esclarecimento.")
        try:
            resultado = executar(turno.conectar())
        except Exception:
            turno.impedimento = "Falha na operação; nenhuma gravação do turno será confirmada."
            raise
        pendente = {**resultado, "status": "pendente"}
        turno.registros.append({"ferramenta": nome, **pendente})
        turno.cache[chave] = pendente
        return pendente


def _validar_resultado_direto(turno: OperacoesTurno, resultado: dict) -> dict:
    from langchain_core.messages import AIMessage, HumanMessage

    texto = json.dumps(resultado, ensure_ascii=False, default=str)
    return no_juiz({
        "messages": [HumanMessage(content=turno.pergunta), AIMessage(content=texto)],
        "evidencias": [texto],
    })
