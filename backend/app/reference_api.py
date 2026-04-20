"""HTTP API для справочника выборов (ParlGov + CLEA, единый reference.duckdb)."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import FileResponse

from pydantic import BaseModel

from app.reference_store import get_reference_store
from app.summary_store import generate_summary, load_summaries

router = APIRouter(prefix="/api/reference", tags=["reference"])


class GenerateSummaryRequest(BaseModel):
    country_code: str
    country_name: str
    anthropic_key: str


@router.get("/summaries")
async def reference_summaries() -> dict[str, object]:
    """Все сохранённые выжимки из избирательных законов."""
    return await asyncio.to_thread(load_summaries)


@router.post("/generate-summary")
async def reference_generate_summary(
    req: GenerateSummaryRequest,
) -> dict[str, object]:
    """Сгенерировать выжимку для одной страны через Claude API."""
    if not req.anthropic_key.strip():
        raise HTTPException(status_code=400, detail="anthropic_key is required")
    if not req.country_code.strip() or not req.country_name.strip():
        raise HTTPException(status_code=400, detail="country_code and country_name are required")
    try:
        return await asyncio.to_thread(
            generate_summary,
            req.country_code.strip(),
            req.country_name.strip(),
            req.anthropic_key.strip(),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}") from e


@router.post("/refresh")
async def reference_refresh(
    force: Annotated[bool, Query(description="Игнорировать Last-Modified / mtime и перекачать всё")] = False,
) -> dict[str, object]:
    """Проверить ParlGov (HTTP) и CLEA (mtime CSV); при необходимости пересобрать reference.duckdb."""
    def run() -> dict[str, object]:
        try:
            return get_reference_store().refresh(force=force)
        except Exception as e:  # noqa: BLE001
            return {"parlgov": {"updated": False, "error": str(e)}, "clea": {}}

    result = await asyncio.to_thread(run)
    status = await asyncio.to_thread(get_reference_store().status)
    return {**result, "status": status}


@router.get("/status")
async def reference_status() -> dict[str, object]:
    return await asyncio.to_thread(get_reference_store().status)


@router.get("/countries")
async def reference_countries() -> list[dict[str, object]]:
    try:
        return await asyncio.to_thread(get_reference_store().list_countries)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/unified-elections")
async def reference_unified_elections(
    country_id: int | None = Query(default=None),
    date_from: Annotated[str | None, Query(description="YYYY-MM-DD")] = None,
    date_to: Annotated[str | None, Query(description="YYYY-MM-DD")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    source: Annotated[str | None, Query(description="parlgov | clea")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    """Список выборов из единой таблицы ref_party_election (ParlGov + CLEA в reference.duckdb)."""
    if source is not None and source not in ("parlgov", "clea"):
        raise HTTPException(status_code=400, detail="source должен быть parlgov или clea.")
    try:
        rows, total = await asyncio.to_thread(
            get_reference_store().list_unified_elections,
            country_id,
            date_from=date_from,
            date_to=date_to,
            q=q,
            source=source,
            limit=limit,
            offset=offset,
        )
        return {"items": rows, "total": total, "limit": limit, "offset": offset}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/duckdb")
async def reference_download_duckdb() -> FileResponse:
    """Скачать единый файл reference.duckdb (ParlGov + CLEA)."""
    st = await asyncio.to_thread(get_reference_store().status)
    if not st.get("parlgov", {}).get("loaded"):
        raise HTTPException(
            status_code=503,
            detail=str(st.get("parlgov", {}).get("error") or "Справочник не загружен."),
        )
    path = get_reference_store().duckdb_file_path()
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Файл DuckDB не найден.")
    return FileResponse(
        str(path),
        filename="reference.duckdb",
        media_type="application/vnd.duckdb.file",
    )


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
            get_reference_store().list_elections,
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
        detail = await asyncio.to_thread(get_reference_store().election_detail, election_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if not detail:
        raise HTTPException(status_code=404, detail="Выборы не найдены.")
    return {**detail, "source": "parlgov"}


@router.get("/election/{election_id:int}/prefill")
async def reference_election_prefill(
    election_id: Annotated[int, Path(ge=1)],
    threshold_percent: Annotated[float, Query(ge=0, le=100)] = 0.0,
) -> dict[str, object]:
    try:
        return await asyncio.to_thread(
            get_reference_store().calculator_prefill,
            election_id,
            threshold_percent=threshold_percent,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        if str(e) == "election_not_found":
            raise HTTPException(status_code=404, detail="Выборы не найдены.") from e
        raise HTTPException(status_code=400, detail="Некорректные данные для калькулятора.") from e


# --- CLEA ---


@router.get("/clea/status")
async def clea_status() -> dict[str, object]:
    st = await asyncio.to_thread(get_reference_store().status)
    return st.get("clea", {})


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
            get_reference_store().clea_list_elections,
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
        detail = await asyncio.to_thread(get_reference_store().clea_election_detail, election_key)
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
            get_reference_store().clea_calculator_prefill,
            election_key,
            threshold_percent=threshold_percent,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        if str(e) == "election_not_found":
            raise HTTPException(status_code=404, detail="Выборы не найдены.") from e
        raise HTTPException(status_code=400, detail="Некорректные данные для калькулятора.") from e
