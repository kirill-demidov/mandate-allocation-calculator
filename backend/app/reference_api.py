"""HTTP API для справочника выборов (ParlGov + CLEA, DuckDB)."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import FileResponse

from app.clea_duckdb import get_clea_store
from app.parlgov_duckdb import get_store

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.post("/refresh")
async def reference_refresh(
    force: Annotated[bool, Query(description="Игнорировать Last-Modified / mtime и перекаать всё")] = False,
) -> dict[str, object]:
    """Проверить ParlGov (HTTP) и CLEA (mtime CSV); при необходимости подтянуть данные и пересобрать DuckDB."""

    def run_parlgov() -> dict[str, object]:
        try:
            return get_store().refresh(force=force)
        except Exception as e:  # noqa: BLE001
            return {"updated": False, "error": str(e)}

    def run_clea() -> dict[str, object]:
        try:
            return get_clea_store().refresh(force=force)
        except Exception as e:  # noqa: BLE001
            return {"updated": False, "error": str(e)}

    parlgov_result = await asyncio.to_thread(run_parlgov)
    clea_result = await asyncio.to_thread(run_clea)
    status = {
        "parlgov": await asyncio.to_thread(get_store().status),
        "clea": await asyncio.to_thread(get_clea_store().status),
    }
    return {
        "parlgov": parlgov_result,
        "clea": clea_result,
        "status": status,
    }


@router.get("/status")
async def reference_status() -> dict[str, object]:
    base = await asyncio.to_thread(get_store().status)
    clea = await asyncio.to_thread(get_clea_store().status)
    return {"parlgov": base, "clea": clea}


@router.get("/countries")
async def reference_countries() -> list[dict[str, object]]:
    try:
        return await asyncio.to_thread(get_store().list_countries)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/elections")
async def reference_elections(
    country_id: int | None = Query(default=None),
    date_from: Annotated[str | None, Query(description="YYYY-MM-DD")] = None,
    date_to: Annotated[str | None, Query(description="YYYY-MM-DD")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    try:
        rows, total = await asyncio.to_thread(
            get_store().list_elections,
            country_id,
            date_from=date_from,
            date_to=date_to,
            q=q,
            limit=limit,
            offset=offset,
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
    detail = dict(detail)
    detail["source"] = "parlgov"
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


# --- CLEA (окружной CSV → агрегат в DuckDB-файл) ---


@router.get("/clea/status")
async def clea_status() -> dict[str, object]:
    return await asyncio.to_thread(get_clea_store().status)


@router.get("/clea/elections")
async def clea_elections(
    date_from: Annotated[str | None, Query(description="YYYY-MM-DD")] = None,
    date_to: Annotated[str | None, Query(description="YYYY-MM-DD")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    try:
        rows, total = await asyncio.to_thread(
            get_clea_store().list_elections,
            date_from=date_from,
            date_to=date_to,
            q=q,
            limit=limit,
            offset=offset,
        )
        return {"items": rows, "total": total, "limit": limit, "offset": offset}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/clea/detail")
async def clea_detail(
    election_key: Annotated[str, Query(min_length=9, max_length=80)],
) -> dict[str, object]:
    try:
        detail = await asyncio.to_thread(get_clea_store().election_detail, election_key)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if not detail:
        raise HTTPException(status_code=404, detail="Выборы не найдены.")
    return detail


@router.get("/clea/prefill")
async def clea_prefill(
    election_key: Annotated[str, Query(min_length=9, max_length=80)],
    threshold_percent: Annotated[float | None, Query(ge=0, le=100)] = None,
) -> dict[str, object]:
    try:
        return await asyncio.to_thread(
            get_clea_store().calculator_prefill,
            election_key,
            threshold_percent=threshold_percent,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        if str(e) == "election_not_found":
            raise HTTPException(status_code=404, detail="Выборы не найдены.") from e
        raise HTTPException(status_code=400, detail="Некорректные данные для калькулятора.") from e


@router.get("/clea/duckdb")
async def clea_download_duckdb() -> FileResponse:
    st = await asyncio.to_thread(get_clea_store().status)
    if not st.get("enabled"):
        raise HTTPException(
            status_code=503,
            detail="CLEA не настроен или ошибка загрузки CSV.",
        )
    path = get_clea_store().duckdb_file_path()
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Файл DuckDB ещё не создан.")
    return FileResponse(
        str(path),
        filename="clea_aggregated.duckdb",
        media_type="application/vnd.duckdb.file",
    )
