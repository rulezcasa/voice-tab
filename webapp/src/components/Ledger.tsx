import { useEffect, useRef, useState } from "react";
import * as api from "../lib/api";
import { absMoney } from "../lib/format";
import type { Activity, GroupBalance, Person } from "../lib/types";
import { ReceiptCard } from "./ReceiptCard";

type Tab = "activity" | "balances";

interface Props {
  open: boolean;
  onClose: () => void;
  people: Person[];
  history: Activity[];
}

/** Bottom sheet: the ledger behind the voice. Drag the handle down or tap outside to close. */
export function Ledger({ open, onClose, people, history }: Props) {
  const [tab, setTab] = useState<Tab>("activity");
  const [drag, setDrag] = useState(0);
  const start = useRef<number | null>(null);
  const [groups, setGroups] = useState<GroupBalance[]>([]);
  const [picked, setPicked] = useState<string | null>(null); // group key (id, or 'none'), 'new' = add form, null = list

  // Refetch group balances whenever the sheet opens on Balances or overall balances change.
  const loadGroups = () =>
    api
      .groupBalances()
      .then(setGroups)
      .catch(() => {});
  useEffect(() => {
    if (open && tab === "balances") loadGroups();
  }, [open, tab, people]);

  const key = (g: GroupBalance) => (g.id === null ? "none" : String(g.id));
  const group = groups.find((g) => key(g) === picked);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const onDown = (e: React.PointerEvent) => {
    start.current = e.clientY;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    if (start.current !== null) setDrag(Math.max(0, e.clientY - start.current));
  };
  const onUp = () => {
    if (drag > 90) onClose();
    start.current = null;
    setDrag(0);
  };

  return (
    <>
      <div className={`scrim ${open ? "open" : ""}`} onClick={onClose} />
      <aside
        className={`sheet ${open ? "open" : ""} ${drag ? "dragging" : ""}`}
        style={drag ? { transform: `translateY(${drag}px)` } : undefined}
        aria-hidden={!open}
        aria-label="Ledger"
      >
        <div
          className="sheet-handle"
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={onUp}
        >
          <span />
        </div>
        <nav className="tabs" role="tablist">
          {(["activity", "balances"] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => {
                setTab(t);
                setPicked(null);
              }}
            >
              {t}
            </button>
          ))}
        </nav>

        <div className="sheet-body">
          {tab === "activity" && (
            <div className="history">
              {history.length === 0 && (
                <p className="empty">
                  Nothing yet. Everything you tell Tab shows up here.
                </p>
              )}
              {[...history].reverse().map((h, i) => (
                <section key={h.receipt.logged_at + i}>
                  <p className="h-heard">“{h.heard}”</p>
                  <ReceiptCard receipt={h.receipt} compact />
                </section>
              ))}
            </div>
          )}

          {tab === "balances" && picked === "new" && (
            <NewGroup
              people={people.filter((p) => !p.is_me)}
              onCancel={() => setPicked(null)}
              onCreated={(id) => loadGroups().then(() => setPicked(String(id)))}
            />
          )}

          {tab === "balances" && !group && picked !== "new" && (
            <>
              <button className="add-group" onClick={() => setPicked("new")}>
                <span aria-hidden="true">+</span> New group
              </button>
              <ul className="rows">
                {groups.length === 0 && (
                  <li className="empty">No balances yet.</li>
                )}
                {groups.map((g) => {
                  const n = Number(g.net);
                  const sign = n > 0.004 ? "pos" : n < -0.004 ? "neg" : "zero";
                  return (
                    <li key={key(g)}>
                      <button
                        className="row group"
                        onClick={() => setPicked(key(g))}
                      >
                        <div className="row-main">
                          <span className="row-title">{g.name}</span>
                          <span className="row-sub">
                            {g.people.length}{" "}
                            {g.people.length === 1 ? "person" : "people"}
                          </span>
                        </div>
                        <span className={`row-amt ${sign}`}>
                          {sign === "pos"
                            ? `you're owed ${absMoney(g.net)}`
                            : sign === "neg"
                              ? `you owe ${absMoney(g.net)}`
                              : "settled"}
                        </span>
                        <span className="chev" aria-hidden="true">
                          ›
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}

          {tab === "balances" && group && (
            <>
              <button className="back" onClick={() => setPicked(null)}>
                ‹ <span>{group.name}</span>
              </button>
              <Balances people={group.people} />
            </>
          )}
        </div>
      </aside>
    </>
  );
}

/** One row per person: who owes, who is owed, with a bar centred on zero. */
function Balances({ people }: { people: Person[] }) {
  const maxAbs = Math.max(1, ...people.map((p) => Math.abs(Number(p.net))));
  return (
    <ul className="rows">
      {people.map((p) => {
        const n = Number(p.net);
        return (
          <li key={p.id} className="row bal">
            <div className="row-main">
              <span className="row-title">{p.is_me ? "You" : p.name}</span>
              <span className="bar">
                <i
                  className={n < 0 ? "neg" : "pos"}
                  style={{ width: `${(Math.abs(n) / maxAbs) * 50}%` }}
                />
              </span>
            </div>
            <span className={`row-amt ${n < 0 ? "neg" : "pos"}`}>
              {n < 0 ? "owes " : "owed "}
              {absMoney(p.net)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** Name a group and tick who's in it. You're always in it, so you aren't listed. */
function NewGroup({
  people,
  onCancel,
  onCreated,
}: {
  people: Person[];
  onCancel: () => void;
  onCreated: (id: number) => void;
}) {
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const toggle = (id: number) =>
    setChosen((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || saving) return;
    setSaving(true);
    setError("");
    try {
      const g = await api.createGroup(name.trim(), [...chosen]);
      onCreated(g.id);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not create the group",
      );
      setSaving(false);
    }
  };

  return (
    <form className="new-group" onSubmit={submit}>
      <button type="button" className="back" onClick={onCancel}>
        ‹ <span>New group</span>
      </button>
      <input
        className="group-name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Group name, e.g. Apt 4B"
        autoFocus
      />
      <p className="pick-label">
        Members <span>· you're included</span>
      </p>
      <ul className="rows">
        {people.map((p) => (
          <li key={p.id}>
            <label className="row pick">
              <span className="row-title">{p.name}</span>
              <input
                type="checkbox"
                checked={chosen.has(p.id)}
                onChange={() => toggle(p.id)}
              />
            </label>
          </li>
        ))}
      </ul>
      {error && <p className="form-error">{error}</p>}
      <button
        className="create"
        type="submit"
        disabled={!name.trim() || saving}
      >
        {saving
          ? "Creating…"
          : chosen.size
            ? `Create with ${chosen.size + 1} people`
            : "Create group"}
      </button>
    </form>
  );
}
