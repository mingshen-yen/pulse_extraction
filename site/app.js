/* Near-fault velocity-pulse extraction — showcase map.
   Data from scripts/build_site_data.py (pipeline) and
   scripts/import_reference_tables.py (published catalogs). No build step. */

const PULSE = "#d62728", NOPULSE = "#6b7f99", FAULT = "#ff7f0e";
const $ = (s) => document.querySelector(s);
const fmt = (x, d = 1) => (x == null || Number.isNaN(+x) ? "–" : (+x).toFixed(d));
const evKey = (n, y) =>
  String(n).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") + (y ? "|" + y : "");

const map = L.map("map", { zoomControl: true }).setView([20, 0], 2);
L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
  { attribution: "Tiles &copy; Esri", maxZoom: 16 }).addTo(map);
L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: 16, opacity: 0.9 }).addTo(map);

const layer = L.layerGroup().addTo(map);
let charts = {}, current = null, fitTarget = null;
const sources = {};        // id -> { label, kind:'pipeline'|'reference', list:[…], docs, citation }
let activeSource = "pipeline";

/* ---------- boot ---------------------------------------------------------- */
async function boot() {
  const [pipe, refIdx] = await Promise.all([
    fetch("data/index.json").then((r) => r.json()),
    fetch("data/reference/index.json").then((r) => r.json()).catch(() => ({ catalogs: [] })),
  ]);

  sources.pipeline = {
    label: "Pipeline results", kind: "pipeline", citation: null,
    list: pipe.events, generated: pipe.generated,
  };
  await Promise.all(refIdx.catalogs.map(async (c) => {
    const doc = await fetch(`data/reference/${c.id}.json`).then((r) => r.json());
    sources[c.id] = {
      label: c.label, kind: "reference", url: c.url, meta: c,
      pulseOnly: !!c.pulse_only,
      list: doc.events, citation: doc.citation,
      docs: Object.fromEntries(doc.events.map((e) => [e.key, e])),
    };
  }));

  buildSourceSelect();
  await setSource("pipeline");
}

function buildSourceSelect() {
  const sel = $("#source");
  sel.innerHTML = "";
  for (const [id, s] of Object.entries(sources)) {
    const n = s.kind === "pipeline" ? s.list.length : s.meta.n_events;
    sel.append(new Option(`${s.label} (${n})`, id));
  }
  sel.onchange = () => setSource(sel.value);
}

async function setSource(id) {
  activeSource = id;
  $("#source").value = id;
  const s = sources[id];
  renderList(s);
  $("#source-note").innerHTML = s.citation
    ? `<b>${s.label}.</b> ${s.citation} ` +
      (s.url ? `<a href="${s.url}" target="_blank" rel="noopener">link</a>` : "")
    : `${s.list.length} events processed end-to-end · updated ` +
      `${(s.generated || "").slice(0, 16).replace("T", " ")} UTC`;
  if (s.list.length) selectEvent(s.list[0].key);
}

function renderList(s) {
  const ul = $("#event-list");
  ul.innerHTML = "";
  s.list.forEach((e) => {
    const np = e.n_pulse ?? e.stats?.n_pulse ?? 0;
    const n = e.n ?? e.stats?.n ?? 0;
    const badge = s.pulseOnly ? `${n} rec` : `${np}/${n}`;
    const li = document.createElement("li");
    li.dataset.key = e.key;
    li.innerHTML =
      `<span class="ev-badge">${badge}</span>` +
      `<div class="ev-name">${e.name}</div>` +
      `<div class="ev-sub">${e.mag_type || "M"} ${fmt(e.mag, 1)} · ` +
      `${(e.time || e.year || "").toString().slice(0, 10)}</div>`;
    li.onclick = () => selectEvent(e.key);
    ul.appendChild(li);
  });
}

/* ---------- select + normalise ----------------------------------------- */
async function selectEvent(key) {
  document.querySelectorAll("#event-list li").forEach((x) =>
    x.classList.toggle("active", x.dataset.key === key));
  const s = sources[activeSource];

  if (s.kind === "pipeline") {
    current = await fetch(`data/events/${key}.json`).then((r) => r.json());
    current.origin = "pipeline";
    current.pulseOnly = false;
  } else {
    const e = s.docs[key];
    current = {
      origin: "reference", pulseOnly: s.pulseOnly,
      event: { name: e.name, lat: e.lat, lon: e.lon, depth_km: e.depth_km,
        mag: e.mag, mag_type: "M", time: e.year, source: s.label,
        fault_type: e.fault_type, fault: e.fault,
        source_model: e.source_model, usgs_url: e.usgs_url },
      stations: e.stations, stats: e.stats, key,
      pipeline: s.label,
    };
  }
  drawMap(current);
  drawHead(current);
  drawCharts(current);
  $("#station-detail").innerHTML =
    '<span class="muted">Select a station' +
    (current.stations.some((x) => x.lat != null) ? " on the map." : " below.") +
    "</span>";
  fillRecordTable(current);
  renderCrossLinks(current);
  requestAnimationFrame(refreshLayout);
}

function findMatch(list, name, yr) {
  const want = evKey(name).split("|")[0];
  const toks = want.split("_").filter((t) => t.length > 3 && !/^\d{4}$/.test(t));
  return list.find((e) => {
    const k = e.key.split("|")[0];
    const yok = !yr || !e.year || Math.abs(+e.year - +yr) <= 1 || k.includes(yr);
    return yok && toks.some((t) => k.includes(t));
  });
}

function renderCrossLinks(d) {
  const el = $("#crosslinks");
  el.innerHTML = "";
  const yr = (d.event.time || "").toString().slice(0, 4);
  const hits = [];
  for (const [id, s] of Object.entries(sources)) {
    if (id === activeSource) continue;
    const m = s.kind === "pipeline"
      ? findMatch(s.list, d.event.name, yr)
      : findMatch(s.list, d.event.name, yr);
    if (m) hits.push({ id, label: s.label, key: m.key });
  }
  if (!hits.length) return;
  el.append(document.createTextNode("also in: "));
  hits.forEach((h, i) => {
    const a = document.createElement("a");
    a.href = "#"; a.textContent = h.label;
    a.onclick = (ev) => { ev.preventDefault(); setSource(h.id).then(() => selectEvent(h.key)); };
    el.append(a);
    if (i < hits.length - 1) el.append(document.createTextNode(" · "));
  });
}

/* ---------- map ------------------------------------------------------------ */
function pgvRadius(pgv) { return 4 + 9 * Math.sqrt(Math.max(pgv || 0, 0) / 120); }

function drawMap(d) {
  layer.clearLayers();
  const ev = d.event, pts = [];

  if (ev.fault && ev.fault.polygon) {
    const f = ev.fault, ff = /finite-fault/.test(f.model || "");
    const poly = f.polygon.map(([lon, lat]) => [lat, lon]);
    L.polygon(poly, { color: FAULT, weight: 2, dashArray: ff ? null : "5 4",
      fillOpacity: ff ? 0.12 : 0.06 })
      .bindTooltip(
        `${ff ? "USGS finite-fault" : "rupture (mag-scaled)"}<br>` +
        `strike ${fmt(f.strike, 0)}° · dip ${fmt(f.dip, 0)}° · ` +
        `${fmt(f.length_km, 0)}×${fmt(f.width_km, 0)} km` +
        (f.max_slip_m ? `<br>max slip ${fmt(f.max_slip_m, 1)} m` : ""),
        { sticky: true }).addTo(layer);
    poly.forEach((p) => pts.push(p));
  }

  if (ev.lat != null) {
    L.marker([ev.lat, ev.lon], {
      icon: L.divIcon({ className: "epi", html: "★", iconSize: [22, 22], iconAnchor: [11, 11] }),
    }).bindPopup(`<b>${ev.name}</b><br>${ev.mag_type || "M"} ${fmt(ev.mag, 1)}` +
      ` · depth ${fmt(ev.depth_km, 0)} km`).addTo(layer);
    pts.push([ev.lat, ev.lon]);
  }

  d.stations.forEach((s) => {
    if (s.lat == null) return;
    const m = L.circleMarker([s.lat, s.lon], {
      radius: pgvRadius(s.PGV), color: "#33404d", weight: 1,
      fillColor: s.is_pulse ? PULSE : "#ffffff",
      fillOpacity: s.is_pulse ? 0.85 : 0.9,
    }).addTo(layer);
    m.bindPopup(
      `<b>${s.code}</b> <span class="muted">${s.network || ""}</span><br>` +
      (s.is_pulse ? `pulse · T<sub>p</sub> ${fmt(s.Tp, 2)} s · PGV ${fmt(s.PGV, 0)} cm/s`
        : `no pulse · PGV ${fmt(s.PGV, 0)} cm/s`) +
      (s.rrup_km != null ? `<br>R<sub>rup</sub> ${fmt(s.rrup_km, 1)} km` : "") +
      (s.repi_km != null ? ` · R<sub>epi</sub> ${fmt(s.repi_km, 0)} km` : ""));
    m.on("click", () => stationDetail(s));
    if (s.is_pulse && s.angle_deg != null) addTick(s);
    if (s.fling) L.circleMarker([s.lat, s.lon], {
      radius: pgvRadius(s.PGV) + 3, color: FAULT, weight: 1.5, fill: false,
    }).bindTooltip("fling step", { sticky: true }).addTo(layer);
    pts.push([s.lat, s.lon]);
  });

  const onlyEpi = pts.length === 1;
  fitTarget = pts.length ? L.latLngBounds(pts).pad(0.15) : null;
  if (fitTarget) map.fitBounds(fitTarget, { padding: [24, 24], maxZoom: onlyEpi ? 8 : 13 });
}

function addTick(s) {
  const a = (s.angle_deg * Math.PI) / 180, km = 4;
  const dlat = (km * Math.cos(a)) / 111.3;
  const dlon = (km * Math.sin(a)) / (111.3 * Math.cos((s.lat * Math.PI) / 180));
  L.polyline([[s.lat - dlat, s.lon - dlon], [s.lat + dlat, s.lon + dlon]],
    { color: PULSE, weight: 2, opacity: 0.7 }).addTo(layer);
}

/* ---------- head + charts + detail ------------------------------------- */
function drawHead(d) {
  const e = d.event, s = d.stats;
  const withco = d.stations.filter((x) => x.lat != null).length;
  const nomap = d.stations.length && withco < d.stations.length;
  $("#event-head").innerHTML =
    `<h3>${e.name}</h3>` +
    `<div class="kv">${e.mag_type || "M"} ${fmt(e.mag, 1)} · ` +
    `${(e.time || "").toString().slice(0, 16).replace("T", " ")} · ` +
    `depth ${fmt(e.depth_km, 0)} km · ${e.source}` +
    (e.fault_type ? ` · ${e.fault_type}` : "") + `</div>` +
    `<div class="stat-row">` +
    (d.pulseOnly
      ? `<div class="stat"><b>${s.n}</b><span>pulse records</span></div>`
      : `<div class="stat"><b>${s.n_pulse}/${s.n}</b><span>pulse-like</span></div>`) +
    `<div class="stat"><b>${fmt(s.Tp_median, 2)} s</b><span>median T<sub>p</sub></span></div>` +
    `<div class="stat"><b>${fmt(s.PGV_median, 0)}</b><span>median PGV cm/s</span></div>` +
    `</div>` +
    (d.pipeline ? `<div class="kv">${d.pipeline}</div>` : "") +
    (e.source_model
      ? `<div class="kv">${e.source_model.source} · nodal plane ` +
        `${fmt(e.source_model.np1[0], 0)}/${fmt(e.source_model.np1[1], 0)}/` +
        `${fmt(e.source_model.np1[2], 0)}` +
        (e.usgs_url ? ` · <a href="${e.usgs_url}" target="_blank" rel="noopener">USGS ↗</a>` : "") +
        `</div>`
      : "") +
    (nomap ? `<div class="kv muted">${withco}/${d.stations.length} stations located — ` +
      `full list below</div>` : "") +
    `<div id="crosslinks" class="kv"></div>`;
}

function scatterCfg(rows, yKey, yLabel) {
  const split = (v) => rows.filter((r) => r.is_pulse === v)
    .map((r) => ({ x: r.rrup_km ?? r.repi_km, y: r[yKey] }))
    .filter((p) => p.x > 0 && p.y > 0);
  return {
    type: "scatter",
    data: { datasets: [
      { label: "pulse", data: split(true), backgroundColor: PULSE, pointRadius: 4 },
      { label: "no pulse", data: split(false), backgroundColor: "#fff",
        borderColor: NOPULSE, borderWidth: 1, pointRadius: 3.5 }] },
    options: { animation: false, plugins: { legend: { display: false } },
      scales: {
        x: { type: "logarithmic", title: { display: true, text: "R_rup / R_epi [km]" } },
        y: { type: "logarithmic", title: { display: true, text: yLabel } } },
      maintainAspectRatio: false },
  };
}

function drawCharts(d) {
  Object.values(charts).forEach((c) => c.destroy());
  const rows = d.stats.scatter || [];
  charts.tp = new Chart($("#c-tp"), scatterCfg(rows, "Tp", "Tp [s]"));
  charts.pgv = new Chart($("#c-pgv"), scatterCfg(rows, "PGV", "PGV [cm/s]"));

  if (d.pulseOnly) {
    $("#frac-cap").textContent = "Tₚ distribution";
    const tps = rows.map((r) => r.Tp).filter((t) => t > 0);
    const edges = [0, 1, 2, 3, 4, 6, 8, 12, 20];
    const counts = edges.slice(1).map((hi, i) =>
      tps.filter((t) => t >= edges[i] && t < hi).length);
    charts.frac = new Chart($("#c-frac"), {
      type: "bar",
      data: { labels: edges.slice(1).map((hi, i) => `${edges[i]}–${hi}`),
        datasets: [{ data: counts, backgroundColor: PULSE }] },
      options: { animation: false, plugins: { legend: { display: false } },
        scales: { y: { title: { display: true, text: "records" } },
          x: { title: { display: true, text: "Tp bin [s]" } } },
        maintainAspectRatio: false },
    });
    return;
  }

  $("#frac-cap").textContent = "pulse fraction by distance";
  const b = d.stats.by_distance || [];
  charts.frac = new Chart($("#c-frac"), {
    type: "bar",
    data: { labels: b.map((x) => `${x.r_lo}–${x.r_hi}`),
      datasets: [{ data: b.map((x) => x.pulse_fraction), backgroundColor: PULSE }] },
    options: { animation: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => {
        const x = b[c.dataIndex];
        return `${x.n_pulse}/${x.n} pulse · med Tp ${fmt(x.Tp_median, 1)} s`; } } } },
      scales: { y: { min: 0, max: 1, title: { display: true, text: "fraction" } },
        x: { title: { display: true, text: "distance bin [km]" } } },
      maintainAspectRatio: false },
  });
}

function stationDetail(s) {
  const g = (k, v) => (v == null || v === "" ? "" : `<span>${k}</span><span>${v}</span>`);
  $("#station-detail").innerHTML =
    `<h4>${s.code} <span class="muted">${s.network || ""}</span></h4>` +
    `<div class="sd-grid">` +
    g("verdict", s.is_pulse ? "<b style='color:#d62728'>pulse</b>" : "no pulse") +
    g("T<sub>p</sub>", s.Tp ? `${fmt(s.Tp, 2)} s` : null) +
    g("PGV", s.PGV ? `${fmt(s.PGV, 1)} cm/s` : null) +
    g("pulse indicator", s.PI != null ? fmt(s.PI, 2) : null) +
    g("orientation", s.angle_deg != null ? `${fmt(s.angle_deg, 0)}°`
      : s.ori_fp != null ? `FN ${fmt(s.ori_fp, 0)}°` : null) +
    g("R<sub>rup</sub>", s.rrup_km != null ? `${fmt(s.rrup_km, 1)} km` : null) +
    g("R<sub>epi</sub>", s.repi_km != null ? `${fmt(s.repi_km, 1)} km` : null) +
    g("V<sub>s30</sub>", s.vs30 ? `${fmt(s.vs30, 0)} m/s` : null) +
    g("fling", s.fling === true ? "yes" : s.fling === false ? "no" : null) +
    g("QC", s.qc) +
    (s.summary_url ? g("", `<a href="${s.summary_url}" target="_blank" ` +
      `rel="noopener">S&amp;B record page ↗</a>`) : "") +
    `</div>` + (s.pulse_trace ? `<canvas id="spark"></canvas>` : "");
  if (s.pulse_trace) spark(s.pulse_trace);
}

/* full record list (shown whenever some stations lack coordinates) */
function fillRecordTable(d) {
  document.querySelectorAll("#panel table.rec-table").forEach((t) => t.remove());
  const withco = d.stations.filter((x) => x.lat != null).length;
  if (!d.stations.length || withco === d.stations.length) return;
  const rows = [...d.stations].sort((a, b) =>
    (a.rrup_km ?? 999) - (b.rrup_km ?? 999));
  const t = document.createElement("table");
  t.className = "rec-table";
  t.innerHTML = "<thead><tr><th>station</th><th>R<sub>rup</sub></th>" +
    "<th>T<sub>p</sub></th><th>PGV</th><th></th></tr></thead>";
  const tb = document.createElement("tbody");
  rows.forEach((s) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${s.lat != null ? "📍 " : ""}${s.code}</td>` +
      `<td>${fmt(s.rrup_km, 1)}</td><td>${fmt(s.Tp, 2)}</td>` +
      `<td>${fmt(s.PGV, 0)}</td><td>${s.is_pulse ? "●" : "○"}</td>`;
    tr.onclick = () => stationDetail(s);
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  $("#station-detail").after(t);
}

function spark(tr) {
  const cv = $("#spark"), ctx = cv.getContext("2d");
  const w = (cv.width = cv.clientWidth), h = (cv.height = 70), v = tr.v;
  const mx = Math.max(...v.map(Math.abs)) || 1;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#c9d2dd"; ctx.beginPath();
  ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
  ctx.strokeStyle = PULSE; ctx.lineWidth = 1.6; ctx.beginPath();
  v.forEach((y, i) => {
    const px = (i / (v.length - 1)) * w, py = h / 2 - (y / mx) * (h / 2 - 4);
    i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
  });
  ctx.stroke();
  ctx.fillStyle = "#889"; ctx.font = "10px sans-serif";
  ctx.fillText(`extracted pulse · ${(v.length * tr.dt).toFixed(0)} s`, 4, 11);
}

function refreshLayout() {
  map.invalidateSize();
  if (fitTarget) map.fitBounds(fitTarget, { padding: [24, 24], maxZoom: 13 });
  Object.values(charts).forEach((c) => c.resize());
}
addEventListener("resize", refreshLayout);

boot().catch((e) => {
  $("#event-list").innerHTML =
    `<li class="muted">Could not load data/ — run the build scripts and serve ` +
    `this folder over http.<br>${e}</li>`;
});
