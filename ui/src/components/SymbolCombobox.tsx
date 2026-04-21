// Searchable typeahead combobox — zero-dep replacement for long <select>
// dropdowns. Used wherever a symbol/option list is too big to scroll
// (Quick Trade, Charts tile, Slot creation, overlays, etc.).
//
// Behavior:
//   * Type to filter (case-insensitive substring match).
//   * Up / Down arrows + Enter to pick.
//   * Esc clears the input + closes.
//   * Click outside closes without changing the value.
//   * Selecting an option closes the dropdown and calls onChange.
//
// Optional `groups` — render options in labeled sections (e.g.
// "Crypto", "Stocks", "Macro") to make a 200-item list scannable.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export interface ComboOption {
  value: string;
  label?: string;
  group?: string;
}

export interface SymbolComboboxProps {
  value: string;
  onChange: (next: string) => void;
  options: string[] | ComboOption[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  /** Maximum number of results to render at a time. Default 80. */
  limit?: number;
  /** When true, allow user to commit a value not in the list (e.g., a custom ticker). */
  allowFreeText?: boolean;
  /** Optional id forwarded to the input for label association. */
  inputId?: string;
}

export function SymbolCombobox({
  value, onChange, options, placeholder,
  className, disabled = false, limit = 80,
  allowFreeText = true, inputId,
}: SymbolComboboxProps) {
  const normalized: ComboOption[] = useMemo(
    () => options.map((o) => (typeof o === "string" ? { value: o, label: o } : o)),
    [options],
  );

  const [open, setOpen] = useState(false);
  const [input, setInput] = useState(value);
  const [highlight, setHighlight] = useState(0);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  // Sync input from external value when not actively editing.
  useEffect(() => { if (!open) setInput(value); }, [value, open]);

  const filtered = useMemo(() => {
    const q = input.trim().toLowerCase();
    if (!q) return normalized.slice(0, limit);
    const matches: ComboOption[] = [];
    for (const o of normalized) {
      const v = o.value.toLowerCase();
      const l = (o.label || o.value).toLowerCase();
      if (v.includes(q) || l.includes(q)) {
        matches.push(o);
        if (matches.length >= limit) break;
      }
    }
    return matches;
  }, [input, normalized, limit]);

  // Reset highlight when filter changes; keep within bounds.
  useEffect(() => {
    setHighlight((h) => (h >= filtered.length ? 0 : h));
  }, [filtered.length]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) {
        setOpen(false);
        setInput(value);
      }
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [open, value]);

  const commit = useCallback((opt: ComboOption | null) => {
    if (opt) {
      onChange(opt.value);
      setInput(opt.value);
    } else if (allowFreeText && input.trim()) {
      onChange(input.trim());
    }
    setOpen(false);
  }, [onChange, input, allowFreeText]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setHighlight((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      commit(filtered[highlight] ?? null);
    } else if (e.key === "Escape") {
      setOpen(false);
      setInput(value);
      inputRef.current?.blur();
    }
  };

  // Group rendering — bucket filtered options by their .group field.
  const grouped = useMemo(() => {
    const buckets = new Map<string, ComboOption[]>();
    for (const o of filtered) {
      const g = o.group || "";
      if (!buckets.has(g)) buckets.set(g, []);
      buckets.get(g)!.push(o);
    }
    return [...buckets.entries()];
  }, [filtered]);

  // Scroll the highlighted row into view.
  useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-idx="${highlight}"]`) as HTMLElement | null;
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [highlight, open]);

  let runningIdx = -1;

  return (
    <div ref={wrapRef} className={`combo ${className ?? ""}`}>
      <input
        id={inputId}
        ref={inputRef}
        type="text"
        className="combo__input"
        value={open ? input : value}
        placeholder={placeholder}
        disabled={disabled}
        onFocus={() => { setOpen(true); setInput(""); }}
        onChange={(e) => { setInput(e.target.value); setOpen(true); }}
        onKeyDown={onKeyDown}
        autoComplete="off"
      />
      {open && (
        <div ref={listRef} className="combo__menu">
          {filtered.length === 0 ? (
            <div className="combo__empty muted small">
              No matches
              {allowFreeText && input.trim() ? <> — press Enter to use "{input.trim()}"</> : null}
            </div>
          ) : (
            grouped.map(([group, opts]) => (
              <div key={group || "_"}>
                {group && <div className="combo__group">{group}</div>}
                {opts.map((o) => {
                  runningIdx += 1;
                  const idx = runningIdx;
                  const isHi = idx === highlight;
                  const isSel = o.value === value;
                  return (
                    <button
                      key={o.value}
                      type="button"
                      data-idx={idx}
                      className={`combo__item ${isHi ? "combo__item--hi" : ""} ${isSel ? "combo__item--sel" : ""}`}
                      onMouseEnter={() => setHighlight(idx)}
                      onClick={() => commit(o)}
                    >
                      <span className="combo__item-value">{o.label || o.value}</span>
                      {o.label && o.label !== o.value && (
                        <span className="combo__item-meta">{o.value}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
