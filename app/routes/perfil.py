from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.perfil import salvar_perfil

router = APIRouter(tags=["perfil"])


class Perfil(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    user_id: str = Field(min_length=1)
    renda_mensal: float = Field(gt=0, strict=True, allow_inf_nan=False)
    objetivo: str = Field(min_length=1, max_length=120)
    tolerancia_risco: Literal["baixa", "media", "alta"]
    preferencias: str = Field(min_length=1)


@router.post("/perfil", response_model=Perfil)
def gravar_perfil(perfil: Perfil):
    try:
        return salvar_perfil(perfil.model_dump())
    except Exception as erro:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível confirmar o salvamento. Tente salvar novamente pela tela Perfil.",
        ) from erro
