/* Near-fault velocity-pulse extraction — showcase map.
   Data from scripts/build_site_data.py (pipeline) and
   scripts/build_reference_catalogs.py (published catalogs), served by the
   D1-backed api/* (functions/api/) when it is there, else read straight from
   data/*.json (no filtering then). No build step. */

const PULSE = "#d62728",
  NOPULSE = "#6b7f99",
  FAULT = "#ff7f0e";
const $ = (s) => document.querySelector(s);
const fmt = (x, d = 1) =>
  x == null || Number.isNaN(+x) ? "–" : (+x).toFixed(d);
const evKey = (n, y) =>
  String(n)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "") + (y ? "|" + y : "");

const map = L.map("map", { zoomControl: true }).setView([20, 0], 2);

const OSM_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const bases = {
  Gray: L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Tiles &copy; Esri", maxZoom: 16 },
  ),
  OpenStreetMap: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: OSM_ATTR,
    maxZoom: 19,
  }),
};
bases["Gray"].addTo(map);
L.control
  .layers(bases, null, { position: "topright", collapsed: false })
  .addTo(map);

const layer = L.layerGroup().addTo(map);
const oriLayer = L.layerGroup().addTo(map);
let charts = {},
  current = null,
  fitTarget = null,
  oriData = [];
const sources = {}; // id -> { label, kind:'pipeline'|'reference', list:[…], docs, citation }
let activeSource = "pipeline";

/* api/* answers -> lists and events come from D1 and can be filtered;
   otherwise (plain static hosting) the data/*.json files are used as-is. */
let API = false;
const FILTERS = ["mag_min", "mag_max", "tp_min", "tp_max", "dist_min", "dist_max"];
const filters = {}; // name -> number, mirrored in the page URL
const query = (extra = {}) => new URLSearchParams({ ...extra, ...filters });
const filtered = () => Object.keys(filters).length > 0;
const getJSON = (url) =>
  fetch(url).then((r) => (r.ok ? r.json() : Promise.reject(new Error(url))));

/* newest event first: full ISO time if present, else the 4-digit year */
const evWhen = (e) => String(e.time || e.year || "");
const byNewest = (events) =>
  [...events].sort((a, b) =>
    evWhen(b) < evWhen(a) ? -1 : evWhen(b) > evWhen(a) ? 1 : 0,
  );

/* ---------- boot ---------------------------------------------------------- */
async function boot() {
  const cats = await getJSON("api/catalogs").catch(() => null);
  if (cats) {
    API = true;
    for (const c of cats.catalogs)
      sources[c.id] = {
        label: c.label,
        kind: c.kind,
        url: c.url,
        meta: c,
        pulseOnly: !!c.pulse_only,
        citation: c.citation || null,
        generated: c.generated,
        list: [],
      };
    readFilters();
    await loadLists();
  } else {
    await bootStatic();
  }
  setupFilterForm();
  buildSourceSelect();
  await setSource("pipeline");
}

/* every source's (filtered) event list; all of them, so "also in" links work */
async function loadLists() {
  await Promise.all(
    Object.entries(sources).map(async ([id, s]) => {
      const d = await getJSON(`api/events?${query({ catalog: id })}`);
      s.list = byNewest(d.events);
      s.nRecords = d.n_records;
    }),
  );
}

async function bootStatic() {
  const [pipe, refIdx] = await Promise.all([
    fetch("data/index.json").then((r) => r.json()),
    fetch("data/reference/index.json")
      .then((r) => r.json())
      .catch(() => ({ catalogs: [] })),
  ]);

  sources.pipeline = {
    label: "Pipeline results",
    kind: "pipeline",
    citation: null,
    list: byNewest(pipe.events),
    generated: pipe.generated,
  };
  await Promise.all(
    refIdx.catalogs.map(async (c) => {
      const doc = await fetch(`data/reference/${c.id}.json`).then((r) =>
        r.json(),
      );
      sources[c.id] = {
        label: c.label,
        kind: "reference",
        url: c.url,
        meta: c,
        pulseOnly: !!c.pulse_only,
        list: byNewest(doc.events),
        citation: doc.citation,
        docs: Object.fromEntries(doc.events.map((e) => [e.key, e])),
      };
    }),
  );
}

/* ---------- filters (API only) ------------------------------------------ */
function readFilters() {
  const p = new URLSearchParams(location.search);
  for (const k of FILTERS) {
    const v = p.get(k);
    if (v != null && v.trim() !== "" && Number.isFinite(+v)) filters[k] = +v;
  }
}

function writeFilterURL() {
  const q = query().toString();
  history.replaceState(null, "", location.pathname + (q ? `?${q}` : "") + location.hash);
}

function setupFilterForm() {
  const form = $("#filters");
  if (!API) {
    form.classList.add("off");
    form.querySelectorAll("input, button").forEach((x) => (x.disabled = true));
    $("#filter-note").textContent = "needs the API (static copy)";
    return;
  }
  for (const k of FILTERS) form.elements[k].value = filters[k] ?? "";
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    for (const k of FILTERS) {
      const v = form.elements[k].value.trim();
      if (v !== "" && Number.isFinite(+v)) filters[k] = +v;
      else delete filters[k];
    }
    await applyFilters();
  };
  form.onreset = () => {
    // runs before the inputs are cleared; apply once they are
    setTimeout(() => form.requestSubmit(), 0);
  };
  noteFilters();
}

async function applyFilters() {
  writeFilterURL();
  $("#filter-note").textContent = "loading…";
  await loadLists();
  noteFilters();
  await setSource(activeSource);
}

function noteFilters() {
  const s = sources[activeSource];
  $("#filter-note").textContent =
    filtered() && s ? `${s.nRecords} matching records` : "";
}

function buildSourceSelect() {
  const sel = $("#source");
  sel.innerHTML = "";
  for (const [id, s] of Object.entries(sources)) {
    const n = API || s.kind !== "pipeline" ? s.meta.n_events : s.list.length;
    sel.append(new Option(`${s.label} (${n})`, id));
  }
  sel.onchange = () => setSource(sel.value);
}

async function setSource(id) {
  activeSource = id;
  $("#source").value = id;
  const s = sources[id];
  renderList(s);
  if (API) noteFilters();
  $("#source-note").innerHTML = s.citation
    ? `<b>${s.label}.</b> ${s.citation} ` +
      (s.url
        ? `<a href="${s.url}" target="_blank" rel="noopener">link</a>`
        : "")
    : `${s.meta?.n_events ?? s.list.length} events processed end-to-end · updated ` +
      `${(s.generated || "").slice(0, 16).replace("T", " ")} UTC`;
  showOverview(s);
}

/* ---------- catalog overview: every epicentre, nothing selected --------- */
function showOverview(s) {
  current = null;
  document
    .querySelectorAll("#event-list li")
    .forEach((x) => x.classList.remove("active"));
  document
    .querySelectorAll("#panel table.rec-table")
    .forEach((t) => t.remove());
  Object.values(charts).forEach((c) => c.destroy());
  charts = {};
  $("#charts").hidden = true;
  drawOverviewMap(s);
  drawOverviewHead(s);
  $("#station-detail").innerHTML =
    '<span class="muted">Select an event from the list or a marker on the map.</span>';
}

function drawOverviewMap(s) {
  layer.clearLayers();
  oriLayer.clearLayers();
  oriData = [];
  const pts = [];
  s.list.forEach((e) => {
    if (e.lat == null) return;
    const np = e.n_pulse ?? e.stats?.n_pulse ?? 0;
    const n = e.n ?? e.stats?.n ?? 0;
    L.marker([e.lat, e.lon], {
      icon: L.divIcon({
        className: "epi epi-small",
        html: "★",
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      }),
    })
      .bindPopup(
        `<b>${e.name}</b><br>${e.mag_type || "M"} ${fmt(e.mag, 1)} · ` +
          `${(e.time || e.year || "").toString().slice(0, 10)}` +
          (n ? `<br>${np}/${n} pulse-like` : ""),
      )
      .on("click", () => selectEvent(e.key))
      .addTo(layer);
    pts.push([e.lat, e.lon]);
  });
  fitTarget = pts.length ? L.latLngBounds(pts).pad(0.15) : null;
  if (fitTarget) map.fitBounds(fitTarget, { padding: [24, 24], maxZoom: 8 });
  else map.setView([20, 0], 2);
}

function drawOverviewHead(s) {
  const n = API || s.kind === "pipeline" ? s.list.length : s.meta.n_events;
  const mapped = s.list.filter((e) => e.lat != null).length;
  $("#event-head").innerHTML =
    `<h3>${s.label}</h3>` +
    `<div class="kv">${n} event${n === 1 ? "" : "s"}` +
    (filtered() ? ` · ${s.nRecords} records match the filters` : "") +
    (mapped < n ? ` · ${mapped} located on the map` : "") +
    `</div>` +
    `<div class="kv muted">Select an event from the list or a marker on the map.</div>`;
}

$("#overview-link").onclick = (ev) => {
  ev.preventDefault();
  showOverview(sources[activeSource]);
};

function renderList(s) {
  const ul = $("#event-list");
  ul.innerHTML = "";
  if (!s.list.length)
    ul.innerHTML = `<li class="muted">No events match the filters.</li>`;
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
  document
    .querySelectorAll("#event-list li")
    .forEach((x) => x.classList.toggle("active", x.dataset.key === key));
  const s = sources[activeSource];

  const doc = API
    ? await getJSON(`api/event?${query({ catalog: activeSource, key })}`)
    : s.kind === "pipeline"
      ? await getJSON(`data/events/${key}.json`)
      : s.docs[key];

  if (s.kind === "pipeline") {
    current = doc;
    current.origin = "pipeline";
    current.pulseOnly = false;
  } else {
    const e = doc;
    current = {
      origin: "reference",
      pulseOnly: s.pulseOnly,
      event: {
        name: e.name,
        lat: e.lat,
        lon: e.lon,
        depth_km: e.depth_km,
        mag: e.mag,
        mag_type: "M",
        time: e.year,
        source: s.label,
        fault_type: e.fault_type,
        fault: e.fault,
        source_model: e.source_model,
        usgs_url: e.usgs_url,
      },
      stations: e.stations,
      stats: e.stats,
      key,
      pipeline: s.label,
    };
  }
  $("#charts").hidden = false;
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
  const toks = want
    .split("_")
    .filter((t) => t.length > 3 && !/^\d{4}$/.test(t));
  return list.find((e) => {
    const k = e.key.split("|")[0];
    const yok =
      !yr || !e.year || Math.abs(+e.year - +yr) <= 1 || k.includes(yr);
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
    const m =
      s.kind === "pipeline"
        ? findMatch(s.list, d.event.name, yr)
        : findMatch(s.list, d.event.name, yr);
    if (m) hits.push({ id, label: s.label, key: m.key });
  }
  if (!hits.length) return;
  el.append(document.createTextNode("also in: "));
  hits.forEach((h, i) => {
    const a = document.createElement("a");
    a.href = "#";
    a.textContent = h.label;
    a.onclick = (ev) => {
      ev.preventDefault();
      setSource(h.id).then(() => selectEvent(h.key));
    };
    el.append(a);
    if (i < hits.length - 1) el.append(document.createTextNode(" · "));
  });
}

/* ---------- map ------------------------------------------------------------ */
function pgvRadius(pgv) {
  return 4 + 9 * Math.sqrt(Math.max(pgv || 0, 0) / 120);
}

function drawMap(d) {
  layer.clearLayers();
  const ev = d.event,
    pts = [];

  if (ev.lat != null) {
    L.marker([ev.lat, ev.lon], {
      icon: L.divIcon({
        className: "epi",
        html: "★",
        iconSize: [22, 22],
        iconAnchor: [11, 11],
      }),
    })
      .bindPopup(
        `<b>${ev.name}</b><br>${ev.mag_type || "M"} ${fmt(ev.mag, 1)}` +
          ` · depth ${fmt(ev.depth_km, 0)} km`,
      )
      .addTo(layer);
    pts.push([ev.lat, ev.lon]);
  }

  oriData = [];
  d.stations.forEach((s) => {
    if (s.lat == null) return;
    const m = L.circleMarker([s.lat, s.lon], {
      radius: pgvRadius(s.PGV),
      color: "#33404d",
      weight: 1,
      fillColor: s.is_pulse ? PULSE : "#ffffff",
      fillOpacity: s.is_pulse ? 0.85 : 0.9,
    }).addTo(layer);
    m.bindPopup(
      `<b>${s.code}</b> <span class="muted">${s.network || ""}</span><br>` +
        (s.is_pulse
          ? `pulse · T<sub>p</sub> ${fmt(s.Tp, 2)} s · PGV ${fmt(s.PGV, 0)} cm/s`
          : `no pulse · PGV ${fmt(s.PGV, 0)} cm/s`) +
        (s.rrup_km != null
          ? `<br>R<sub>rup</sub> ${fmt(s.rrup_km, 1)} km`
          : "") +
        (s.repi_km != null ? ` · R<sub>epi</sub> ${fmt(s.repi_km, 0)} km` : ""),
    );
    m.on("click", () => stationDetail(s));
    if (s.fling)
      L.circleMarker([s.lat, s.lon], {
        radius: pgvRadius(s.PGV) + 3,
        color: FAULT,
        weight: 1.5,
        fill: false,
      })
        .bindTooltip("fling step", { sticky: true })
        .addTo(layer);
    const ori = s.angle_deg != null ? s.angle_deg : s.ori_n;
    if (s.is_pulse && ori != null) oriData.push([s, ori]);
    pts.push([s.lat, s.lon]);
  });
  redrawTicks();

  const onlyEpi = pts.length === 1;
  fitTarget = pts.length ? L.latLngBounds(pts).pad(0.15) : null;
  if (fitTarget)
    map.fitBounds(fitTarget, { padding: [24, 24], maxZoom: onlyEpi ? 8 : 13 });
}

/* screen-constant double-ended bar through each pulse marker, along the pulse
   (fault-normal) polarization axis.  oriDeg is the azimuth from North. */
function redrawTicks() {
  oriLayer.clearLayers();
  if (map.getZoom() < 5) return;
  oriData.forEach(([s, oriDeg]) => {
    const a = (oriDeg * Math.PI) / 180;
    const c = map.latLngToLayerPoint([s.lat, s.lon]);
    const half = pgvRadius(s.PGV) + 7; // px
    const dx = half * Math.sin(a),
      dy = -half * Math.cos(a);
    const p = [
      map.layerPointToLatLng([c.x - dx, c.y - dy]),
      map.layerPointToLatLng([c.x + dx, c.y + dy]),
    ];
    const az = ((Math.round(oriDeg) % 180) + 180) % 180;
    L.polyline(p, {
      color: "#fff",
      weight: 4,
      opacity: 0.9,
      lineCap: "round",
    }).addTo(oriLayer);
    L.polyline(p, {
      color: "#1c2733",
      weight: 2,
      opacity: 0.95,
      lineCap: "round",
    })
      .bindTooltip(`${s.code} · pulse orientation ${az}° from N`, {
        sticky: true,
      })
      .addTo(oriLayer);
  });
}
map.on("zoomend", redrawTicks);

/* ---------- head + charts + detail ------------------------------------- */
function drawHead(d) {
  const e = d.event,
    s = d.stats;
  const withco = d.stations.filter((x) => x.lat != null).length;
  const nomap = d.stations.length && withco < d.stations.length;
  $("#event-head").innerHTML =
    `<h3>${e.name}</h3>` +
    `<div class="kv">${e.mag_type || "M"} ${fmt(e.mag, 1)} · ` +
    `${(e.time || "").toString().slice(0, 16).replace("T", " ")} · ` +
    `depth ${fmt(e.depth_km, 0)} km · ${e.source}` +
    (e.fault_type ? ` · ${e.fault_type}` : "") +
    `</div>` +
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
        (e.usgs_url
          ? ` · <a href="${e.usgs_url}" target="_blank" rel="noopener">USGS ↗</a>`
          : "") +
        `</div>`
      : "") +
    (nomap
      ? `<div class="kv muted">${withco}/${d.stations.length} stations located — ` +
        `full list below</div>`
      : "") +
    `<div id="crosslinks" class="kv"></div>`;
}

/* distance for every plot: Rrup, or Rhyp when a station has no Rrup */
const plotDist = (r) => (r.rrup_km != null ? r.rrup_km : r.rhyp_km);

function scatterCfg(rows, yKey, yLabel) {
  const split = (v) =>
    rows
      .filter((r) => r.is_pulse === v)
      .map((r) => ({ x: plotDist(r), y: r[yKey] }))
      .filter((p) => p.x > 0 && p.y > 0);
  return {
    type: "scatter",
    data: {
      datasets: [
        {
          label: "pulse",
          data: split(true),
          backgroundColor: PULSE,
          pointRadius: 4,
        },
        {
          label: "no pulse",
          data: split(false),
          backgroundColor: "#fff",
          borderColor: NOPULSE,
          borderWidth: 1,
          pointRadius: 3.5,
        },
      ],
    },
    options: {
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          type: "logarithmic",
          title: { display: true, text: "R_rup [km]" },
        },
        y: { type: "logarithmic", title: { display: true, text: yLabel } },
      },
      maintainAspectRatio: false,
    },
  };
}

function drawCharts(d) {
  Object.values(charts).forEach((c) => c.destroy());
  const rows = d.stats.scatter || [];
  charts.tp = new Chart($("#c-tp"), scatterCfg(rows, "Tp", "Tp [s]"));
  charts.pgv = new Chart($("#c-pgv"), scatterCfg(rows, "PGV", "PGV [cm/s]"));
}

function stationDetail(s) {
  const g = (k, v) =>
    v == null || v === "" ? "" : `<span>${k}</span><span>${v}</span>`;
  $("#station-detail").innerHTML =
    `<h4>${s.code} <span class="muted">${s.network || ""}</span></h4>` +
    `<div class="sd-grid">` +
    g(
      "verdict",
      s.is_pulse ? "<b style='color:#d62728'>pulse</b>" : "no pulse",
    ) +
    g("T<sub>p</sub>", s.Tp ? `${fmt(s.Tp, 2)} s` : null) +
    g("PGV", s.PGV ? `${fmt(s.PGV, 1)} cm/s` : null) +
    g("pulse indicator", s.PI != null ? fmt(s.PI, 2) : null) +
    g(
      "orientation",
      (s.angle_deg != null ? s.angle_deg : s.ori_n) != null
        ? `${fmt(((Math.round(s.angle_deg != null ? s.angle_deg : s.ori_n) % 180) + 180) % 180, 0)}° from N` +
            (s.ori_fp != null ? ` · ${fmt(s.ori_fp, 0)}° from FP` : "")
        : null,
    ) +
    g("R<sub>rup</sub>", s.rrup_km != null ? `${fmt(s.rrup_km, 1)} km` : null) +
    g("R<sub>epi</sub>", s.repi_km != null ? `${fmt(s.repi_km, 1)} km` : null) +
    g("V<sub>s30</sub>", s.vs30 ? `${fmt(s.vs30, 0)} m/s` : null) +
    g("fling", s.fling === true ? "yes" : s.fling === false ? "no" : null) +
    g("QC", s.qc) +
    (s.summary_url
      ? g(
          "",
          `<a href="${s.summary_url}" target="_blank" ` +
            `rel="noopener">S&amp;B record page ↗</a>`,
        )
      : "") +
    `</div>` +
    (s.pulse_trace ? `<canvas id="spark"></canvas>` : "");
  if (s.pulse_trace) spark(s.pulse_trace);
}

/* full record list (shown whenever some stations lack coordinates) */
function fillRecordTable(d) {
  document
    .querySelectorAll("#panel table.rec-table")
    .forEach((t) => t.remove());
  const withco = d.stations.filter((x) => x.lat != null).length;
  if (!d.stations.length || withco === d.stations.length) return;
  const rows = [...d.stations].sort(
    (a, b) => (a.rrup_km ?? 999) - (b.rrup_km ?? 999),
  );
  const t = document.createElement("table");
  t.className = "rec-table";
  t.innerHTML =
    "<thead><tr><th>station</th><th>R<sub>rup</sub></th>" +
    "<th>T<sub>p</sub></th><th>PGV</th><th></th></tr></thead>";
  const tb = document.createElement("tbody");
  rows.forEach((s) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${s.lat != null ? "📍 " : ""}${s.code}</td>` +
      `<td>${fmt(s.rrup_km, 1)}</td><td>${fmt(s.Tp, 2)}</td>` +
      `<td>${fmt(s.PGV, 0)}</td><td>${s.is_pulse ? "●" : "○"}</td>`;
    tr.onclick = () => stationDetail(s);
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  $("#station-detail").after(t);
}

function spark(tr) {
  const cv = $("#spark"),
    ctx = cv.getContext("2d");
  const w = (cv.width = cv.clientWidth),
    h = (cv.height = 70),
    v = tr.v;
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
    i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
  });
  ctx.stroke();
  ctx.fillStyle = "#889";
  ctx.font = "10px sans-serif";
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
