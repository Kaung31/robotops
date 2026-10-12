"""Durable campaign definitions, execution, cancellation and reconciliation."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response
from fastapi.responses import HTMLResponse

from ..models import ControlOptions
from .models import CampaignDefinition, CampaignEvent, CampaignRecord, CampaignRuntimeStatus
from .report_models import CampaignReport
from .reports import build_report, render_html
from .repository import CampaignConflict, CampaignRepository, CampaignStorageError
from .service import CampaignService


def validate_options(definition: CampaignDefinition, options: ControlOptions) -> None:
    if definition.world not in {world.id for world in options.worlds}:
        raise ValueError("Unknown campaign world")
    profiles = {profile.id for profile in options.navigation_profiles}
    if not set(definition.profiles) <= profiles:
        raise ValueError("Unknown navigation profile")
    if not any(
        item.id == definition.map_id and item.world_id == definition.world for item in options.maps
    ):
        raise ValueError("Campaign requires a saved map with matching environment metadata")


def campaign_router(
    repository: CampaignRepository,
    get_options: Callable[[], ControlOptions],
    service: CampaignService,
    artifact_root: Path,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])

    def call(operation, *args):
        try:
            return operation(*args)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Campaign not found") from exc
        except CampaignConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CampaignStorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("", response_model=CampaignRecord, status_code=201)
    def create(
        definition: CampaignDefinition,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
        ] = None,
    ) -> CampaignRecord:
        existing = call(repository.find_by_key, idempotency_key) if idempotency_key else None
        if existing is not None:
            if existing.definition != definition:
                raise HTTPException(
                    status_code=409, detail="Idempotency key reused with different content"
                )
            response.status_code = 200
            response.headers["Location"] = f"/api/v1/campaigns/{existing.id}"
            return existing
        try:
            validate_options(definition, get_options())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        record, created = call(repository.create, definition, idempotency_key)
        if not created:
            response.status_code = 200
        response.headers["Location"] = f"/api/v1/campaigns/{record.id}"
        return record

    @router.get("", response_model=list[CampaignRecord])
    def history(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0, le=9223372036854775807)] = 0,
    ) -> list[CampaignRecord]:
        return call(repository.history, limit, offset)

    @router.get("/runtime", response_model=CampaignRuntimeStatus)
    def runtime_status() -> CampaignRuntimeStatus:
        lease = call(repository.lease)
        return CampaignRuntimeStatus(
            worker_active=bool(
                lease
                and service.active_id == lease["campaign_id"]
                and service.task
                and not service.task.done()
            ),
            execution_enabled=service.enabled,
            supported_modes=[mode for mode in ("mock", "sim") if service.runtime.supports(mode)],
            campaign_id=lease["campaign_id"] if lease else None,
        )

    @router.get("/{campaign_id}", response_model=CampaignRecord)
    def get(campaign_id: str) -> CampaignRecord:
        return call(repository.get, campaign_id)

    @router.get("/{campaign_id}/events", response_model=list[CampaignEvent])
    def events(
        campaign_id: str,
        after: Annotated[int, Query(ge=0, le=9223372036854775807)] = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[CampaignEvent]:
        return call(repository.events, campaign_id, after, limit)

    @router.post("/{campaign_id}/reports", response_model=CampaignReport)
    def generate_report(campaign_id: str) -> CampaignReport:
        record = call(repository.get, campaign_id)
        return call(repository.save_report, call(build_report, record, artifact_root))

    @router.get("/{campaign_id}/reports", response_model=list[CampaignReport])
    def reports(campaign_id: str, limit: Annotated[int, Query(ge=1, le=100)] = 20):
        return call(repository.reports, campaign_id, limit)

    @router.get("/{campaign_id}/reports/{report_id}", response_model=CampaignReport)
    def get_report(campaign_id: str, report_id: str):
        return call(repository.get_report, campaign_id, report_id)

    @router.get("/{campaign_id}/reports/{report_id}/download")
    def download_report(
        campaign_id: str,
        report_id: str,
        format: Annotated[str, Query(pattern="^(json|html)$")] = "json",
    ):
        report = call(repository.get_report, campaign_id, report_id)
        headers = {
            "Content-Disposition": f'attachment; filename="robotops-report-{report.id}.{format}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        }
        if format == "html":
            headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'unsafe-inline'; sandbox"
            )
            return HTMLResponse(render_html(report), headers=headers)
        return Response(
            report.model_dump_json(indent=2), media_type="application/json", headers=headers
        )

    @router.post("/{campaign_id}/cancel", response_model=CampaignRecord)
    def cancel(campaign_id: str) -> CampaignRecord:
        return call(repository.cancel, campaign_id)

    @router.post("/{campaign_id}/start", response_model=CampaignRecord, status_code=202)
    async def start(campaign_id: str) -> CampaignRecord:
        try:
            record = await asyncio.to_thread(call, repository.get, campaign_id)
            validate_options(record.definition, get_options())
            return await service.start(campaign_id)
        except NotImplementedError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/{campaign_id}/reconcile", response_model=CampaignRecord)
    async def reconcile(campaign_id: str) -> CampaignRecord:
        await asyncio.to_thread(call, repository.get, campaign_id)
        return await service.reconcile(campaign_id)

    return router
