from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match, Mount
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import validar_config, FRONTEND_DIR
from app.routes import chat, sessions, monitor, perfil

for _problema in validar_config():
    print(f"[config] ATENÇÃO: {_problema}")

app = FastAPI(
    title="Assessor IA",
    description="Assessor financeiro e de agenda com LangChain e LangGraph.",
    version="0.1.0",
)

app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(monitor.router)
app.include_router(perfil.router)


@app.middleware("http")
async def validar_rota_api(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    caminho = request.scope["path"]
    canonico = caminho.rstrip("/") or "/"
    rotas = [*chat.router.routes, *sessions.router.routes,
             *monitor.router.routes, *perfil.router.routes, *app.routes]
    for rota in rotas:
        if isinstance(rota, Mount) or not hasattr(rota, "methods"):
            continue
        escopo = {**request.scope, "path": canonico}
        match, _ = rota.matches(escopo)
        if match == Match.NONE:
            continue
        if caminho != canonico:
            destino = request.url.replace(path=canonico)
            return RedirectResponse(str(destino), status_code=307)
        if match == Match.PARTIAL:
            permitidos = sorted(rota.methods or [])
            return JSONResponse(status_code=405, headers={"Allow": ", ".join(permitidos)}, content={
                "status": 405, "detail": "Método não permitido. Use " + ", ".join(permitidos) + ".",
                "rota": caminho, "metodo": request.method,
            })
        break
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def erro_http(request: Request, erro: StarletteHTTPException):
    detalhe = erro.detail
    if erro.status_code in {404, 405}:
        detalhe = "Rota não encontrada. Confira a URL e os métodos em /docs."
    return JSONResponse(status_code=erro.status_code, headers=erro.headers, content={
        "status": erro.status_code, "detail": detalhe,
        "rota": request.url.path, "metodo": request.method,
    })


@app.get("/health")
def health() -> dict:
    problemas = validar_config()
    return {
        "status": "ok" if not problemas else "atencao",
        "problemas_de_configuracao": problemas,
    }


app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
