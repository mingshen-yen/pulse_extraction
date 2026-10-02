import { type FormEvent, type ReactNode } from "react";

import { FILTER_KEYS, type Catalog, type EventSummary, type FilterKey, type Filters } from "../api";
import { evDate, fmt } from "../util";

function SourceNote({ cat }: { cat: Catalog }) {
  if (cat.citation)
    return (
      <p className="muted" id="source-note">
        <b>{cat.label}.</b> {cat.citation}{" "}
        {cat.url && (
          <a href={cat.url} target="_blank" rel="noopener">
            link
          </a>
        )}
      </p>
    );
  return (
    <p className="muted" id="source-note">
      {cat.n_events} events processed end-to-end · updated{" "}
      {(cat.generated || "").slice(0, 16).replace("T", " ")} UTC
    </p>
  );
}

const ROWS: { label: ReactNode; min: FilterKey; max: FilterKey; step: string; title?: string }[] = [
  { label: "M", min: "mag_min", max: "mag_max", step: "0.1" },
  { label: <>T<sub>p</sub> [s]</>, min: "tp_min", max: "tp_max", step: "0.1" },
  { label: "R [km]", min: "dist_min", max: "dist_max", step: "1",
    title: "Rrup, or Rhyp where Rrup is not available" },
];

function FilterForm({ filters, note, onApply }: {
  filters: Filters; note: string; onApply: (f: Filters) => void;
}) {
  const submit = (ev: FormEvent<HTMLFormElement>) => {
    ev.preventDefault();
    const data = new FormData(ev.currentTarget);
    const f: Filters = {};
    for (const k of FILTER_KEYS) {
      const v = String(data.get(k) ?? "").trim();
      if (v !== "" && Number.isFinite(+v)) f[k] = +v;
    }
    onApply(f);
  };
  // keyed on the applied filters so the inputs reset when they change from outside
  return (
    <form id="filters" autoComplete="off" onSubmit={submit} key={JSON.stringify(filters)}>
      <span className="lbl">Filter records</span>
      {ROWS.map((r) => (
        <label className="f-row" key={r.min} title={r.title}>
          <span>{r.label}</span>
          <input name={r.min} type="number" step={r.step} placeholder="min" defaultValue={filters[r.min] ?? ""} />
          <span>–</span>
          <input name={r.max} type="number" step={r.step} placeholder="max" defaultValue={filters[r.max] ?? ""} />
        </label>
      ))}
      <div className="f-actions">
        <button type="submit">Apply</button>
        <button type="button" onClick={() => onApply({})}>
          Reset
        </button>
        <span id="filter-note" className="muted">
          {note}
        </span>
      </div>
    </form>
  );
}

export default function Sidebar(props: {
  catalogs: Catalog[];
  active: string;
  events: EventSummary[];
  selectedKey: string | null;
  filters: Filters;
  filterNote: string;
  error: string | null;
  onSource: (id: string) => void;
  onApply: (f: Filters) => void;
  onOverview: () => void;
  onSelectEvent: (key: string) => void;
}) {
  const cat = props.catalogs.find((c) => c.id === props.active);
  return (
    <aside id="events">
      <label htmlFor="source" className="lbl">
        Data source
      </label>
      <select id="source" value={props.active} onChange={(e) => props.onSource(e.target.value)}>
        {props.catalogs.map((c) => (
          <option key={c.id} value={c.id}>
            {c.label} ({c.n_events})
          </option>
        ))}
      </select>
      {cat && <SourceNote cat={cat} />}
      <FilterForm filters={props.filters} note={props.filterNote} onApply={props.onApply} />
      <h2>
        Events{" "}
        <a
          href="#"
          id="overview-link"
          onClick={(e) => {
            e.preventDefault();
            props.onOverview();
          }}
        >
          show all on map
        </a>
      </h2>
      <ul id="event-list">
        {props.error ? (
          <li className="muted">
            Could not load the data API (api/catalogs). Locally, run <code>wrangler pages dev</code>.
            <br />
            {props.error}
          </li>
        ) : cat && !props.events.length ? (
          <li className="muted">No events match the filters.</li>
        ) : (
          props.events.map((e) => (
            <li
              key={e.key}
              className={e.key === props.selectedKey ? "active" : undefined}
              onClick={() => props.onSelectEvent(e.key)}
            >
              <span className="ev-badge">{cat?.pulse_only ? `${e.n} rec` : `${e.n_pulse}/${e.n}`}</span>
              <div className="ev-name">{e.name}</div>
              <div className="ev-sub">
                {e.mag_type || "M"} {fmt(e.mag, 1)} · {evDate(e)}
              </div>
            </li>
          ))
        )}
      </ul>
    </aside>
  );
}
