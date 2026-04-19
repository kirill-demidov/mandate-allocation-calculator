from __future__ import annotations

import io
import os
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.calc import calculate_mandates
from app.reference_api import router as reference_router

METHOD_KEYS = (
    "hare",
    "droop",
    "sainte_lague",
    "dhondt",
    "imperiali",
)


def _parse_cors_origins(raw: str | None) -> list[str]:
    if not raw:
        return [
            "http://localhost",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "https://electoral-calc.org",
            "https://www.electoral-calc.org",
        ]
    return [o.strip() for o in raw.split(",") if o.strip()]


class PartyRow(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    vote_percent: float = Field(..., ge=0, le=100)


class CalculateRequest(BaseModel):
    total_mandates: int = Field(..., ge=1, le=10_000)
    threshold_percent: float = Field(0, ge=0, le=100)
    parties: list[PartyRow] = Field(..., min_length=1)

    @field_validator("parties")
    @classmethod
    def unique_names(cls, v: list[PartyRow]) -> list[PartyRow]:
        names = [p.name for p in v]
        if len(names) != len(set(names)):
            raise ValueError("Названия партий должны быть уникальными.")
        return v


class MandateRow(BaseModel):
    party: str
    vote_percent: float
    hare: int
    droop: int
    sainte_lague: int
    dhondt: int
    imperiali: int


class CalculateResponse(BaseModel):
    rows: list[MandateRow]
    vote_percent_sum: float


app = FastAPI(title="Mandate allocation API", version="1.0.0")
app.include_router(reference_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(os.getenv("CORS_ORIGINS")),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/calculate", response_model=CalculateResponse)
def calculate(body: CalculateRequest) -> CalculateResponse:
    total_pct = float(sum(p.vote_percent for p in body.parties))
    if total_pct > 100.0 + 1e-9:
        raise HTTPException(
            status_code=400,
            detail=f"Сумма процентов не может превышать 100%. Сейчас: {total_pct:.4f}",
        )
    names = [p.name for p in body.parties]
    votes = np.array([p.vote_percent for p in body.parties], dtype=float)
    try:
        mandates = calculate_mandates(
            votes, body.total_mandates, body.threshold_percent
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    rows: list[MandateRow] = []
    for i, name in enumerate(names):
        rows.append(
            MandateRow(
                party=name,
                vote_percent=float(votes[i]),
                hare=int(mandates["hare"][i]),
                droop=int(mandates["droop"][i]),
                sainte_lague=int(mandates["sainte_lague"][i]),
                dhondt=int(mandates["dhondt"][i]),
                imperiali=int(mandates["imperiali"][i]),
            )
        )
    return CalculateResponse(rows=rows, vote_percent_sum=total_pct)


@app.post("/api/export.xlsx")
def export_excel(
    body: CalculateRequest,
    lang: Literal["ru", "en"] = Query("ru"),
) -> StreamingResponse:
    """Тот же расчёт, что и /api/calculate, в виде Excel."""
    res = calculate(body)
    labels = {
        "ru": {
            "party": "Партия",
            "votes": "Голоса (%)",
            "hare": "Хэйр",
            "droop": "Друпа",
            "sl": "Сент-Лагю",
            "dhondt": "Д'Ондт",
            "imp": "Империали",
        },
        "en": {
            "party": "Party",
            "votes": "Votes (%)",
            "hare": "Hare",
            "droop": "Droop",
            "sl": "Sainte-Laguë",
            "dhondt": "D'Hondt",
            "imp": "Imperiali",
        },
    }[lang]
    df = pd.DataFrame(
        [
            {
                labels["party"]: r.party,
                labels["votes"]: r.vote_percent,
                labels["hare"]: r.hare,
                labels["droop"]: r.droop,
                labels["sl"]: r.sainte_lague,
                labels["dhondt"]: r.dhondt,
                labels["imp"]: r.imperiali,
            }
            for r in res.rows
        ]
    )
    total_row = {
        labels["party"]: ("Итого" if lang == "ru" else "Total"),
        labels["votes"]: df[labels["votes"]].sum(),
        labels["hare"]: int(df[labels["hare"]].sum()),
        labels["droop"]: int(df[labels["droop"]].sum()),
        labels["sl"]: int(df[labels["sl"]].sum()),
        labels["dhondt"]: int(df[labels["dhondt"]].sum()),
        labels["imp"]: int(df[labels["imp"]].sum()),
    }
    df = pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")
    buf.seek(0)
    filename = "results.xlsx" if lang == "en" else "результаты.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
