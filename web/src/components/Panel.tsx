import {
  Chart as ChartJS, LinearScale, LogarithmicScale, PointElement, Tooltip, type ChartOptions,
} from "chart.js";
import { useEffect, useRef, type ReactNode } from "react";
import { Scatter } from "react-chartjs-2";

import type { Catalog, EventView, ScatterRow, Station } from "../api";
import { NOPULSE, PULSE, axis180, fmt, orientation, plotDist } from "../util";

ChartJS.register(LinearScale, LogarithmicScale, PointElement, Tooltip);

export interface CrossLink {
  catalog: string;
  label: string;
  key: string;
}

/* ---------- heads ------------------------------------------------------- */
export function OverviewHead({ cat, nEvents, nRecords, nMapped, filtered }: {
  cat: Catalog; nEvents: number; nRecords: number; nMapped: number; filtered: boolean;
}) {
  return (
    <div id="event-head">
      <h3>{cat.label}</h3>
      <div className="kv">
        {nEvents} event{nEvents === 1 ? "" : "s"}
        {filtered && ` · ${nRecords} records match the filters`}
        {nMapped < nEvents && ` · ${nMapped} located on the map`}
      </div>
      <div className="kv muted">Select an event from the list or a marker on the map.</div>
    </div>
  );
}

function EventHead({ view, links, onLink }: {
  view: EventView; links: CrossLink[]; onLink: (l: CrossLink) => void;
}) {
  const e = view.event,
    s = view.stats;
  const withco = view.stations.filter((x) => x.lat != null).length;
  const nomap = view.stations.length > 0 && withco < view.stations.length;
  const sm = e.source_model;
  return (
    <div id="event-head">
      <h3>{e.name}</h3>
      <div className="kv">
        {e.mag_type || "M"} {fmt(e.mag, 1)} · {(e.time || "").slice(0, 16).replace("T", " ")} · depth{" "}
        {fmt(e.depth_km, 0)} km · {e.source}
        {e.fault_type && ` · ${e.fault_type}`}
      </div>
      <div className="stat-row">
        {view.pulseOnly ? (
          <div className="stat">
            <b>{s.n}</b>
            <span>pulse records</span>
          </div>
        ) : (
          <div className="stat">
            <b>
              {s.n_pulse}/{s.n}
            </b>
            <span>pulse-like</span>
          </div>
        )}
        <div className="stat">
          <b>{fmt(s.Tp_median, 2)} s</b>
          <span>
            median T<sub>p</sub>
          </span>
        </div>
        <div className="stat">
          <b>{fmt(s.PGV_median, 0)}</b>
          <span>median PGV cm/s</span>
        </div>
      </div>
      {view.pipeline && <div className="kv">{view.pipeline}</div>}
      {sm && (
        <div className="kv">
          {sm.source} · nodal plane {fmt(sm.np1[0], 0)}/{fmt(sm.np1[1], 0)}/{fmt(sm.np1[2], 0)}
          {e.usgs_url && (
            <>
              {" · "}
              <a href={e.usgs_url} target="_blank" rel="noopener">
                USGS ↗
              </a>
            </>
          )}
        </div>
      )}
      {nomap && (
        <div className="kv muted">
          {withco}/{view.stations.length} stations located — full list below
        </div>
      )}
      <div id="crosslinks" className="kv">
        {links.length > 0 && "also in: "}
        {links.map((l, i) => (
          <span key={l.catalog}>
            <a
              href="#"
              onClick={(ev) => {
                ev.preventDefault();
                onLink(l);
              }}
            >
              {l.label}
            </a>
            {i < links.length - 1 && " · "}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ---------- station detail ---------------------------------------------- */
function Spark({ trace }: { trace: { dt: number; v: number[] } }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    const w = (cv.width = cv.clientWidth),
      h = (cv.height = 70),
      v = trace.v;
    const mx = Math.max(...v.map(Math.abs)) || 1;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = "#c9d2dd";
    ctx.beginPath();
    ctx.moveTo(0, h / 2);
    ctx.lineTo(w, h / 2);
    ctx.stroke();
    ctx.strokeStyle = PULSE;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    v.forEach((y, i) => {
      const px = (i / (v.length - 1)) * w,
        py = h / 2 - (y / mx) * (h / 2 - 4);
      if (i) ctx.lineTo(px, py);
      else ctx.moveTo(px, py);
    });
    ctx.stroke();
    ctx.fillStyle = "#889";
    ctx.font = "10px sans-serif";
    ctx.fillText(`extracted pulse · ${(v.length * trace.dt).toFixed(0)} s`, 4, 11);
  }, [trace]);
  return <canvas id="spark" ref={ref} />;
}

function StationDetail({ s }: { s: Station }) {
  const ori = orientation(s);
  const rows: [ReactNode, ReactNode][] = [
    ["verdict", s.is_pulse ? <b style={{ color: PULSE }}>pulse</b> : "no pulse"],
    [<>T<sub>p</sub></>, s.Tp ? `${fmt(s.Tp, 2)} s` : null],
    ["PGV", s.PGV ? `${fmt(s.PGV, 1)} cm/s` : null],
    ["pulse indicator", s.PI != null ? fmt(s.PI, 2) : null],
    ["orientation", ori != null
      ? `${axis180(ori)}° from N` + (s.ori_fp != null ? ` · ${fmt(s.ori_fp, 0)}° from FP` : "")
      : null],
    [<>R<sub>rup</sub></>, s.rrup_km != null ? `${fmt(s.rrup_km, 1)} km` : null],
    [<>R<sub>epi</sub></>, s.repi_km != null ? `${fmt(s.repi_km, 1)} km` : null],
    [<>V<sub>s30</sub></>, s.vs30 ? `${fmt(s.vs30, 0)} m/s` : null],
    ["fling", s.fling === true ? "yes" : s.fling === false ? "no" : null],
    ["QC", s.qc],
    ["", s.summary_url ? (
      <a href={s.summary_url} target="_blank" rel="noopener">S&amp;B record page ↗</a>
    ) : null],
  ];
  return (
    <>
      <h4>
        {s.code} <span className="muted">{s.network || ""}</span>
      </h4>
      <div className="sd-grid">
        {rows.map(([k, v], i) =>
          v == null || v === "" ? null : (
            <span key={i} style={{ display: "contents" }}>
              <span>{k}</span>
              <span>{v}</span>
            </span>
          ),
        )}
      </div>
      {s.pulse_trace && <Spark trace={s.pulse_trace} />}
    </>
  );
}

/* full record list, shown whenever some stations lack coordinates */
function RecordTable({ stations, onSelect }: { stations: Station[]; onSelect: (s: Station) => void }) {
  const rows = [...stations].sort((a, b) => (a.rrup_km ?? 999) - (b.rrup_km ?? 999));
  return (
    <table className="rec-table">
      <thead>
        <tr>
          <th>station</th>
          <th>
            R<sub>rup</sub>
          </th>
          <th>
            T<sub>p</sub>
          </th>
          <th>PGV</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((s) => (
          <tr key={s.code} onClick={() => onSelect(s)}>
            <td>
              {s.lat != null ? "📍 " : ""}
              {s.code}
            </td>
            <td>{fmt(s.rrup_km, 1)}</td>
            <td>{fmt(s.Tp, 2)}</td>
            <td>{fmt(s.PGV, 0)}</td>
            <td>{s.is_pulse ? "●" : "○"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ---------- charts ------------------------------------------------------ */
function ScatterChart({ rows, yKey, yLabel }: { rows: ScatterRow[]; yKey: "Tp" | "PGV"; yLabel: string }) {
  const split = (v: boolean) =>
    rows
      .filter((r) => r.is_pulse === v)
      .map((r) => ({ x: plotDist(r) ?? 0, y: r[yKey] ?? 0 }))
      .filter((p) => p.x > 0 && p.y > 0);
  const options: ChartOptions<"scatter"> = {
    animation: false,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { type: "logarithmic", title: { display: true, text: "R_rup [km]" } },
      y: { type: "logarithmic", title: { display: true, text: yLabel } },
    },
  };
  return (
    <Scatter
      options={options}
      data={{
        datasets: [
          { label: "pulse", data: split(true), backgroundColor: PULSE, pointRadius: 4 },
          { label: "no pulse", data: split(false), backgroundColor: "#fff", borderColor: NOPULSE,
            borderWidth: 1, pointRadius: 3.5 },
        ],
      }}
    />
  );
}

/* ---------- panel ------------------------------------------------------- */
export default function Panel({ head, view, station, links, onLink, onSelectStation }: {
  head: ReactNode;
  view: EventView | null;
  station: Station | null;
  links: CrossLink[];
  onLink: (l: CrossLink) => void;
  onSelectStation: (s: Station) => void;
}) {
  const someUnmapped = view && view.stations.length > 0 && view.stations.some((x) => x.lat == null);
  return (
    <aside id="panel">
      {view ? <EventHead view={view} links={links} onLink={onLink} /> : head}
      <div id="station-detail" className={station ? undefined : "muted"}>
        {station ? (
          <StationDetail s={station} />
        ) : (
          <span className="muted">
            {!view
              ? "Select an event from the list or a marker on the map."
              : view.stations.some((x) => x.lat != null)
                ? "Select a station on the map."
                : "Select a station below."}
          </span>
        )}
      </div>
      {view && someUnmapped && <RecordTable stations={view.stations} onSelect={onSelectStation} />}
      {view && (
        <div id="charts">
          <figure>
            <figcaption>
              T<sub>p</sub> vs R<sub>rup</sub>
            </figcaption>
            <div className="chart-box">
              <ScatterChart rows={view.stats.scatter || []} yKey="Tp" yLabel="Tp [s]" />
            </div>
          </figure>
          <figure>
            <figcaption>
              PGV vs R<sub>rup</sub>
            </figcaption>
            <div className="chart-box">
              <ScatterChart rows={view.stats.scatter || []} yKey="PGV" yLabel="PGV [cm/s]" />
            </div>
          </figure>
        </div>
      )}
    </aside>
  );
}
