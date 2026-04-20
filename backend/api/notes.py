"""/notes — research + trading notes."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.notes_store import Note, NoteAttachment, NotesStore

router = APIRouter(tags=["notes"])


def get_notes_store() -> NotesStore:
    raise HTTPException(status_code=503, detail="NotesStore not configured")


StoreDep = Annotated[NotesStore, Depends(get_notes_store)]


class NoteAttachmentOut(BaseModel):
    id: int | None
    kind: str
    path: str
    meta: dict[str, Any] = Field(default_factory=dict)


class NoteOut(BaseModel):
    id: str
    title: str
    body_md: str
    tags: list[str] = Field(default_factory=list)
    linked_layout_id: str | None = None
    linked_backtest_id: str | None = None
    attachments: list[NoteAttachmentOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NoteCreate(BaseModel):
    title: str
    body_md: str = ""
    tags: list[str] = Field(default_factory=list)
    linked_layout_id: str | None = None
    linked_backtest_id: str | None = None


class NoteUpdate(BaseModel):
    title: str | None = None
    body_md: str | None = None
    tags: list[str] | None = None
    linked_layout_id: str | None = None
    linked_backtest_id: str | None = None


class AttachmentCreate(BaseModel):
    path: str
    kind: str = "file"
    meta: dict[str, Any] = Field(default_factory=dict)


def _att_out(a: NoteAttachment) -> NoteAttachmentOut:
    return NoteAttachmentOut(id=a.id, kind=a.kind, path=a.path, meta=a.meta)


def _to_out(n: Note) -> NoteOut:
    return NoteOut(
        id=n.id, title=n.title, body_md=n.body_md, tags=n.tags,
        linked_layout_id=n.linked_layout_id, linked_backtest_id=n.linked_backtest_id,
        attachments=[_att_out(a) for a in n.attachments],
        created_at=n.created_at, updated_at=n.updated_at,
    )


@router.get("/notes", response_model=list[NoteOut])
def list_notes(store: StoreDep, tag: str | None = None) -> list[NoteOut]:
    return [_to_out(n) for n in store.list(tag=tag)]


@router.post("/notes", response_model=NoteOut)
def create_note(req: NoteCreate, store: StoreDep) -> NoteOut:
    return _to_out(store.create(**req.model_dump()))


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: str, store: StoreDep) -> NoteOut:
    n = store.get(note_id)
    if n is None:
        raise HTTPException(status_code=404, detail=f"Note not found: {note_id}")
    return _to_out(n)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: str, req: NoteUpdate, store: StoreDep) -> NoteOut:
    n = store.update(note_id, req.model_dump(exclude_unset=True))
    if n is None:
        raise HTTPException(status_code=404, detail=f"Note not found: {note_id}")
    return _to_out(n)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: str, store: StoreDep) -> None:
    store.delete(note_id)


@router.post("/notes/{note_id}/attachments", response_model=NoteAttachmentOut)
def attach(note_id: str, req: AttachmentCreate, store: StoreDep) -> NoteAttachmentOut:
    if store.get(note_id) is None:
        raise HTTPException(status_code=404, detail=f"Note not found: {note_id}")
    try:
        att = store.add_attachment(note_id, path=req.path, kind=req.kind, meta=req.meta)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _att_out(att)
