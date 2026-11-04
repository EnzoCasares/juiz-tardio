from typing import List, Optional

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.operacoes import conexao_leitura, gravar_validado, turno_atual


class AddEventArgs(BaseModel):
    title: str = Field(..., description="Título do evento.")
    source_text: str = Field(..., description="Texto original do usuário.")
    start_time: str = Field(..., description="Início em ISO 8601 com fuso horário.")
    end_time: Optional[str] = Field(default=None, description="Fim em ISO 8601.")
    location: Optional[str] = Field(default=None, description="Local do evento.")
    notes: Optional[str] = Field(default=None, description="Observações adicionais.")


@tool("add_event", args_schema=AddEventArgs)
def add_event(
    title: str,
    source_text: str,
    start_time: str,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Insere um evento na agenda local, armazenada no Postgres."""
    turno = turno_atual()
    origem = turno.pergunta if turno is not None else source_text
    argumentos = dict(title=title, source_text=origem, start_time=start_time,
                      end_time=end_time, location=location, notes=notes)

    def executar(conn):
        with conn.cursor() as cur:
            cur.execute(
            """
            INSERT INTO events
                (title, start_time, end_time, location, notes, source_text)
            VALUES
                (%s, %s::timestamptz, %s::timestamptz, %s, %s, %s)
            RETURNING id, start_time, end_time;
            """,
                (title, start_time, end_time, location, notes, origem),
            )
            new_id, start, end = cur.fetchone()
        return {
            "id": new_id,
            "title": title,
            "start_time": str(start),
            "end_time": str(end) if end else None,
        }
    return gravar_validado("add_event", argumentos, executar)


class QueryEventsArgs(BaseModel):
    text: Optional[str] = Field(
        default=None,
        description="Texto para busca em título, local, notas ou texto original.",
    )
    date_local: Optional[str] = Field(
        default=None,
        description="Data local YYYY-MM-DD em America/Sao_Paulo.",
    )
    date_from_local: Optional[str] = Field(default=None, description="Data inicial inclusiva.")
    date_to_local: Optional[str] = Field(default=None, description="Data final inclusiva.")
    limit: int = Field(default=20, ge=1, le=200)


@tool("query_events", args_schema=QueryEventsArgs)
def query_events(
    text: Optional[str] = None,
    date_local: Optional[str] = None,
    date_from_local: Optional[str] = None,
    date_to_local: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Consulta eventos por texto e datas locais antes de confirmar disponibilidade."""
    with conexao_leitura() as conn, conn.cursor() as cur:
        if date_local and (date_from_local or date_to_local):
            return {
                "status": "error",
                "message": "Use date_local OU (date_from_local/date_to_local), não ambos.",
            }

        where_sql = "WHERE 1=1"
        params: dict = {"limit": limit}
        if text:
            where_sql += (
                " AND (e.title ILIKE %(text_like)s"
                " OR e.location ILIKE %(text_like)s"
                " OR e.notes ILIKE %(text_like)s"
                " OR e.source_text ILIKE %(text_like)s)"
            )
            params["text_like"] = f"%{text}%"
        if date_local:
            where_sql += (
                " AND e.start_time >= (%(date_local)s::date AT TIME ZONE 'America/Sao_Paulo')"
                " AND e.start_time < ((%(date_local)s::date + INTERVAL '1 day')"
                " AT TIME ZONE 'America/Sao_Paulo')"
            )
            params["date_local"] = date_local
        else:
            if date_from_local:
                where_sql += (
                    " AND e.start_time >= (%(date_from)s::date AT TIME ZONE 'America/Sao_Paulo')"
                )
                params["date_from"] = date_from_local
            if date_to_local:
                where_sql += (
                    " AND e.start_time < ((%(date_to)s::date + INTERVAL '1 day')"
                    " AT TIME ZONE 'America/Sao_Paulo')"
                )
                params["date_to"] = date_to_local

        cur.execute(
            f"""
            SELECT e.id, e.title, e.start_time, e.end_time, e.location,
                   e.notes, e.source_text, e.recorded_at
            FROM events e
            {where_sql}
            ORDER BY e.start_time ASC
            LIMIT %(limit)s;
            """,
            params,
        )
        results: List[dict] = []
        for row in cur.fetchall():
            results.append(
                {
                    "id": row[0],
                    "title": row[1],
                    "start_time": str(row[2]),
                    "end_time": str(row[3]) if row[3] else None,
                    "location": row[4],
                    "notes": row[5],
                    "source_text": row[6],
                    "recorded_at": str(row[7]),
                }
            )
        return {"status": "ok", "count": len(results), "results": results}


TOOLS_AGENDA = [add_event, query_events]
