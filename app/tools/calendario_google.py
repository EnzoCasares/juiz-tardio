from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from langchain.tools import tool
from pydantic import BaseModel, Field
from app.operacoes import bloquear, turno_atual

from app.config import (
    BASE_DIR,
    GOOGLE_CALENDAR_ACCESS_TOKEN,
    GOOGLE_CALENDAR_MCP_URL,
    GOOGLE_OAUTH_CREDENTIALS,
)

ESCOPOS = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]
ARQUIVO_TOKEN = BASE_DIR / "google-calendar.token.json"
CABECALHOS_MCP = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
}


def _credenciais_oauth() -> Optional[str]:
    if not GOOGLE_OAUTH_CREDENTIALS:
        return None
    caminho = Path(GOOGLE_OAUTH_CREDENTIALS)
    if not caminho.is_absolute():
        caminho = BASE_DIR / caminho
    return str(caminho) if caminho.is_file() else None


def _salvar_token(creds) -> None:
    ARQUIVO_TOKEN.write_text(creds.to_json(), encoding="utf-8")


def _carregar_token():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not ARQUIVO_TOKEN.is_file():
        return None
    creds = Credentials.from_authorized_user_file(str(ARQUIVO_TOKEN), ESCOPOS)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _salvar_token(creds)
    return creds if creds and creds.valid else None


def autenticar() -> dict:
    from google_auth_oauthlib.flow import InstalledAppFlow

    keys = _credenciais_oauth()
    if not keys:
        return {
            "status": "error",
            "message": "Falta gcp-oauth.keys.json na raiz do projeto.",
        }
    flow = InstalledAppFlow.from_client_secrets_file(keys, ESCOPOS)
    creds = flow.run_local_server(port=0, prompt="consent")
    _salvar_token(creds)
    return {"status": "ok", "arquivo": str(ARQUIVO_TOKEN)}


def _access_token() -> Optional[str]:
    if GOOGLE_CALENDAR_ACCESS_TOKEN:
        return GOOGLE_CALENDAR_ACCESS_TOKEN
    creds = _carregar_token()
    return creds.token if creds else None


def _resultado_mcp(result: Any) -> dict:
    if getattr(result, "structured_content", None):
        data = result.structured_content
        return data if isinstance(data, dict) else {"status": "ok", "result": data}
    textos = [
        bloco.text
        for bloco in (getattr(result, "content", []) or [])
        if getattr(bloco, "text", None)
    ]
    if not textos:
        return {"status": "error", "message": "O servidor MCP não devolveu conteúdo."}
    try:
        return json.loads(textos[0])
    except json.JSONDecodeError:
        return {"status": "ok", "result": textos[0]}


def _erro_mcp(result: Any) -> dict:
    conteudo = _resultado_mcp(result)
    mensagem = conteudo.get("result") or conteudo.get("message") or conteudo
    return {
        "status": "error",
        "message": mensagem if isinstance(mensagem, str) else str(mensagem),
    }


def _motivo(erro: BaseException) -> str:
    if isinstance(erro, BaseExceptionGroup):
        return " | ".join(_motivo(sub) for sub in erro.exceptions)
    texto = str(erro).strip()
    return f"{type(erro).__name__}: {texto}" if texto else type(erro).__name__


async def _chamar_via_http(nome: str, argumentos: dict) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    token = _access_token()
    if not token:
        return {
            "status": "error",
            "message": (
                "Sem token do Google Calendar. Rode no terminal: "
                "python -c \"from app.tools.calendario_google import autenticar; "
                "print(autenticar())\""
            ),
        }
    client = create_mcp_http_client()
    client.headers["Authorization"] = f"Bearer {token}"
    async with client:
        async with streamable_http_client(
            GOOGLE_CALENDAR_MCP_URL,
            http_client=client,
        ) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(nome, argumentos)
                if getattr(result, "is_error", False):
                    return _erro_mcp(result)
                return _resultado_mcp(result)


def _executar(coro_factory) -> dict:
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro_factory())).result()


def _criar_via_rest(payload: dict) -> dict:
    import httpx

    token = _access_token()
    if not token:
        return {
            "status": "error",
            "message": "Sem token do Google Calendar. Execute autenticar().",
        }
    corpo = {
        "summary": payload["summary"],
        "start": {
            "dateTime": payload["startTime"],
            "timeZone": payload.get("timeZone", "America/Sao_Paulo"),
        },
        "end": {
            "dateTime": payload["endTime"],
            "timeZone": payload.get("timeZone", "America/Sao_Paulo"),
        },
    }
    if payload.get("location"):
        corpo["location"] = payload["location"]
    if payload.get("description"):
        corpo["description"] = payload["description"]
    resposta = httpx.post(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers={"Authorization": f"Bearer {token}", "content-type": "application/json"},
        json=corpo,
        timeout=30,
    )
    data = resposta.json()
    if resposta.status_code >= 400:
        return {
            "status": "error",
            "message": data.get("error", {}).get("message") or str(data),
        }
    return {
        "status": "ok",
        "id": data.get("id"),
        "titulo": data.get("summary"),
        "inicio": (data.get("start") or {}).get("dateTime"),
        "link": data.get("htmlLink"),
    }


def chamar_google_calendar(nome_tool: str, argumentos: dict) -> dict:
    try:
        resposta = _executar(lambda: _chamar_via_http(nome_tool, argumentos))
    except Exception as exc:
        resposta = {"status": "error", "message": _motivo(exc)}
    texto = str(resposta.get("message") or "")
    if resposta.get("status") != "error":
        return resposta
    if (
        "Calendar MCP API has not been used" in texto
        or "calendarmcp.googleapis.com" in texto
        or "Server returned an error" in texto
    ):
        return _criar_via_rest(argumentos)
    return resposta


def listar_tools_google() -> dict:
    import httpx

    resposta = httpx.post(
        GOOGLE_CALENDAR_MCP_URL,
        headers=CABECALHOS_MCP,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        timeout=30,
    )
    return resposta.json()


def _fim_padrao(start_time: str) -> str:
    try:
        return (datetime.fromisoformat(start_time) + timedelta(hours=1)).isoformat()
    except ValueError:
        return start_time


class AddGoogleEventArgs(BaseModel):
    title: str = Field(..., description="Título do evento no Google Calendar.")
    start_time: str = Field(..., description="Início em ISO 8601 com fuso.")
    end_time: Optional[str] = Field(default=None, description="Fim em ISO 8601.")
    location: Optional[str] = Field(default=None, description="Local.")
    description: Optional[str] = Field(default=None, description="Descrição ou notas.")


@tool("add_google_event", args_schema=AddGoogleEventArgs)
def add_google_event(
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """Solicita criação no Google somente após aprovação e commit do evento local."""
    turno = turno_atual()
    if turno is None:
        return bloquear("Use o chat para autorizar o evento antes de enviá-lo ao Google.")
    with turno.lock:
        if turno.impedimento:
            return bloquear(turno.impedimento)
        locais = [
            r for r in turno.registros
            if r["ferramenta"] == "add_event" and r["title"] == title
            and datetime.fromisoformat(r["start_time"]) == datetime.fromisoformat(start_time)
            and (not end_time or r.get("end_time") is not None
                 and datetime.fromisoformat(r["end_time"]) == datetime.fromisoformat(end_time))
        ]
        if not locais:
            return bloquear("O Google exige um evento local autorizado com título e horários iguais.")
        local = locais[0]
        inicio = datetime.fromisoformat(local["start_time"]).isoformat()
        fim = local.get("end_time") or _fim_padrao(inicio)
        fim = datetime.fromisoformat(fim).isoformat()
        dados = dict(title=title, start_time=inicio, end_time=fim,
                     location=location, description=description)
        if not any(r["title"] == title and r["start_time"] == inicio and r["end_time"] == fim
                   for r in turno.google):
            turno.google.append(dados)
        return {"status": "pendente", "message": "Google ainda não executado; aguardando juiz e commit local."}


def criar_evento_google_aprovado(
    title: str, start_time: str, end_time: Optional[str] = None,
    location: Optional[str] = None, description: Optional[str] = None,
) -> dict:
    fim = end_time or _fim_padrao(start_time)
    payload: dict[str, Any] = {
        "summary": title,
        "startTime": start_time,
        "endTime": fim,
        "timeZone": "America/Sao_Paulo",
    }
    if location:
        payload["location"] = location
    if description:
        payload["description"] = description
    bruto = chamar_google_calendar("create_event", payload)
    if bruto.get("status") == "ok" and bruto.get("id"):
        return {
            "status": "ok",
            "id": bruto["id"],
            "titulo": bruto.get("titulo") or title,
            "inicio": bruto.get("inicio") or start_time,
            "link": bruto.get("link"),
        }
    evento = bruto.get("event", bruto) if isinstance(bruto, dict) else None
    if isinstance(evento, dict) and evento.get("id") and evento.get("status") not in {"error", "cancelled"}:
        return {
            "status": "ok",
            "id": evento["id"],
            "titulo": evento.get("summary"),
            "inicio": (evento.get("start") or {}).get("dateTime") or evento.get("start"),
            "link": evento.get("htmlLink") or evento.get("html_link"),
        }
    return bruto


TOOLS_GOOGLE = [add_google_event]
