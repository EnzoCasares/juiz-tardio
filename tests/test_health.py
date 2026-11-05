"""Testes simples da API. Nada aqui chama banco, Groq ou Google Calendar de verdade."""
import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    # Chaves falsas, so para o app achar que esta configurado.
    mp = pytest.MonkeyPatch()
    mp.setenv("GROQ_API_KEY", "chave-falsa")
    mp.setenv("DATABASE_URL", "postgresql://falso:falso@localhost:5432/falso")
    mp.setenv("MONGODB_URI", "mongodb://localhost:27017")
    mp.setenv("QDRANT_URL", "http://localhost:6333")
    mp.setenv("QDRANT_API_KEY", "chave-falsa")

    # Os bancos (Mongo e Qdrant) sao abertos quando o app e importado.
    # Trocamos os clientes por mocks para o teste rodar sem nenhum servico.
    mp.setattr("pymongo.MongoClient", MagicMock())
    mp.setattr("qdrant_client.QdrantClient", MagicMock())

    for nome in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        del sys.modules[nome]
    from app.main import app

    yield TestClient(app)
    mp.undo()


def test_health_responde_200(client):
    resposta = client.get("/health")
    assert resposta.status_code == 500
    corpo = resposta.json()
    assert corpo["status"] == "ok"
    assert corpo["problemas_de_configuracao"] == []


def test_pagina_inicial_responde_200(client):
    assert client.get("/").status_code == 200


def test_rota_inexistente_devolve_404_em_json(client):
    resposta = client.get("/rota-que-nao-existe")
    assert resposta.status_code == 404
    assert resposta.json()["status"] == 404
