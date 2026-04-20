// Notes page — interactive research notebooks with screenshot attachments.
// Phase 13 shell — CRUD + markdown editor + screenshot insert.
// The full "interactive widgets embedded in a note" flow lands later.

import { useCallback, useEffect, useState } from "react";

import { notes } from "../api/endpoints";
import type { Note } from "../api/endpoints";

export function NotesPage() {
  const [list, setList] = useState<Note[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<Note> | null>(null);
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(() => {
    notes.list().then(setList).catch(() => setList([]));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const selected = list.find((n) => n.id === selectedId) ?? null;

  useEffect(() => {
    if (selected) {
      setDraft({
        id: selected.id,
        title: selected.title,
        body_md: selected.body_md,
        tags: selected.tags,
      });
    } else {
      setDraft(null);
    }
  }, [selected?.id]);

  const createNote = async () => {
    const title = prompt("Note title:") ?? "";
    if (!title.trim()) return;
    const n = await notes.create({ title, body_md: `# ${title}\n\n` });
    await refresh();
    setSelectedId(n.id);
  };

  const save = async () => {
    if (!draft?.id) return;
    setSaving(true);
    try {
      await notes.update(draft.id, {
        title: draft.title ?? "",
        body_md: draft.body_md ?? "",
        tags: draft.tags ?? [],
      });
      await refresh();
    } finally {
      setSaving(false);
    }
  };

  const del = async () => {
    if (!selectedId) return;
    if (!confirm("Delete this note?")) return;
    await notes.delete(selectedId);
    setSelectedId(null);
    refresh();
  };

  const insertScreenshot = async () => {
    if (!draft?.id || !draft.body_md !== undefined) return;
    const path = prompt(
      "Chart screenshot path (Phase 13 will wire this to the live chart canvas):",
      "data/notes/" + draft.id + "/shot1.png",
    );
    if (!path) return;
    const att = await notes.attach(draft.id, { path, kind: "screenshot" });
    const insert = `\n\n![screenshot](${att.path})\n`;
    setDraft({ ...draft, body_md: (draft.body_md ?? "") + insert });
  };

  return (
    <div className="page">
      <h1 className="page__title">Notes</h1>
      <div className="outcomes-layout">
        <aside className="outcomes-board card">
          <div className="outcomes-board__header">
            <h2 className="card__title">Notebook</h2>
            <button onClick={createNote} title="New note">+ New</button>
          </div>
          {list.length === 0 ? (
            <p className="muted">No notes yet.</p>
          ) : (
            <ul className="market-list">
              {list.map((n) => (
                <li
                  key={n.id}
                  className={`market-list__item ${n.id === selectedId ? "is-selected" : ""}`}
                >
                  <button onClick={() => setSelectedId(n.id)}>
                    <span className="market-list__sym">{n.title}</span>
                    <span className="market-list__meta muted small">
                      {(n.tags ?? []).join(", ") || "—"} · {n.updated_at?.slice(0, 10) ?? ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="outcomes-detail">
          {!draft ? (
            <div className="card">
              <p className="muted">Pick a note on the left, or create a new one.</p>
            </div>
          ) : (
            <>
              <section className="card">
                <div className="chart-toolbar">
                  <label className="field" style={{ flex: 1 }}>
                    <span>Title</span>
                    <input
                      value={draft.title ?? ""}
                      onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                    />
                  </label>
                  <label className="field">
                    <span>Tags (comma-sep)</span>
                    <input
                      value={(draft.tags ?? []).join(", ")}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          tags: e.target.value
                            .split(",")
                            .map((s) => s.trim())
                            .filter(Boolean),
                        })
                      }
                    />
                  </label>
                  <button onClick={insertScreenshot} title="Insert chart screenshot placeholder">
                    + Screenshot
                  </button>
                  <button onClick={save} disabled={saving}>
                    {saving ? "saving…" : "Save"}
                  </button>
                  <button onClick={del}>Delete</button>
                </div>
              </section>
              <section className="card">
                <h3 className="card__title">Body (markdown)</h3>
                <textarea
                  value={draft.body_md ?? ""}
                  onChange={(e) => setDraft({ ...draft, body_md: e.target.value })}
                  rows={20}
                  style={{
                    width: "100%",
                    fontFamily: "SFMono-Regular, Consolas, monospace",
                    fontSize: 13,
                    background: "var(--bg)",
                    color: "var(--fg)",
                    border: "1px solid var(--border)",
                    borderRadius: 4,
                    padding: 10,
                  }}
                />
              </section>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
