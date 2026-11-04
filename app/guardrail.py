import re
import unicodedata

_PADRAO_CPF = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}")
_PADRAO_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

_PALAVRAS_BLOQUEADAS = ["ignore as instrucoes", "prompt do sistema"]


def anonimizar_entrada(texto: str) -> tuple[str, dict]:
    mapa_pii: dict[str, str] = {}

    def _tokenizar(prefixo: str, valor: str) -> str:
        token = f"[{prefixo}_{len(mapa_pii)}]"
        mapa_pii[token] = valor
        return token

    texto_anonimizado = _PADRAO_CPF.sub(lambda m: _tokenizar("CPF", m.group()), texto)
    texto_anonimizado = _PADRAO_EMAIL.sub(lambda m: _tokenizar("EMAIL", m.group()), texto_anonimizado)
    return texto_anonimizado, mapa_pii


def guardrail_entrada(texto: str) -> bool:
    texto_lower = "".join(c for c in unicodedata.normalize("NFKD", texto.casefold())
                          if not unicodedata.combining(c))
    return any(palavra in texto_lower for palavra in _PALAVRAS_BLOQUEADAS)


def guardrail_saida(resposta: str, mapa_pii: dict) -> str:
    for token, valor in mapa_pii.items():
        if valor in resposta:
            resposta = resposta.replace(valor, token)
    return resposta
