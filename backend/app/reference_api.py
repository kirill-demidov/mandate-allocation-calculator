"""HTTP API для справочника выборов (ParlGov + DuckDB)."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from app.parlgov_duckdb import get_store

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/status")
async def reference_status() -> dict[str, object]:
    return await asyncio.to_thread(get_store().status)


@router.get("/countries")
async def reference_countries() -> list[dict[str, object]]:
    try:
        return await asyncio.to_thread(get_store().list_countries)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/elections")
async def reference_elections(
    country_id: Annotated[int, Query(ge=1)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    try:
        rows, total = await asyncio.to_thread(
            get_store().list_elections, country_id, limit=limit, offset=offset
        )
        return {"items": rows, "total": total, "limit": limit, "offset": offset}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/election/{election_id:int}")
async def reference_election_detail(
    election_id: Annotated[int, Path(ge=1)],
) -> dict[str, object]:
    try:
        detail = await asyncio.to_thread(get_store().election_detail, election_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if not detail:
        raise HTTPException(status_code=404, detail="Выборы не найдены.")
    return detail


@router.get("/election/{election_id:int}/prefill")
async def reference_election_prefill(
    election_id: Annotated[int, Path(ge=1)],
    threshold_percent: Annotated[float, Query(ge=0, le=100)] = 0.0,
) -> dict[str, object]:
    try:
        return await asyncio.to_thread(
            get_store().calculator_prefill,
            election_id,
            threshold_percent=threshold_percent,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        if str(e) == "election_not_found":
            raise HTTPException(status_code=404, detail="Выборы не найдены.") from e
        raise HTTPException(status_code=400, detail="Некорректные данные для калькулятора.") from e
