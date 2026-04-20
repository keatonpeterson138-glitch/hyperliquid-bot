"""/audit — queryable append-only log of all trading events."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.models.audit import AuditEventOut, AuditResponse
from backend.services.audit import AuditService

router = APIRouter(tags=["audit"])


def get_audit_service() -> AuditService:
    raise HTTPException(status_code=503, detail="AuditService not configured")


AuditDep = Annotated[AuditService, Depends(get_audit_service)]


@router.get("/audit", response_model=AuditResponse)
def query_audit(
    svc: AuditDep,
    event_type: Annotated[list[str] | None, Query()] = None,
    symbol: str | None = None,
    slot_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 1000,
) -> AuditResponse:
    events = svc.query(
        event_types=event_type,
        symbol=symbol,
        slot_id=slot_id,
        since=since,
        until=until,
        limit=limit,
    )
    return AuditResponse(
        total=svc.count(),
        events=[AuditEventOut(**e.__dict__) for e in events],
    )


@router.get("/audit.csv")
def audit_csv(
    svc: AuditDep,
    event_type: Annotated[list[str] | None, Query()] = None,
    symbol: str | None = None,
    slot_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100_000,
) -> StreamingResponse:
    events = svc.query(
        event_types=event_type,
        symbol=symbol,
        slot_id=slot_id,
        since=since,
        until=until,
        limit=limit,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id", "ts", "event_type", "source", "slot_id", "strategy",
            "symbol", "side", "size_usd", "price", "reason",
        ]
    )
    for e in events:
        writer.writerow(
            [
                e.id,
                e.ts.isoformat(),
                e.event_type,
                e.source,
                e.slot_id or "",
                e.strategy or "",
                e.symbol or "",
                e.side or "",
                e.size_usd if e.size_usd is not None else "",
                e.price if e.price is not None else "",
                e.reason or "",
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit.csv"},
    )
