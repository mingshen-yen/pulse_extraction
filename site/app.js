/* Near-fault velocity-pulse extraction — showcase map.
   Reads data/index.json + data/events/<key>.json produced by
   scripts/build_site_data.py. No build step. */

const PULSE = "#d62728", NOPULSE = "#6b7f99", FAULT = "#ff7f0e";
const $ = (s) => document.querySelector(s);

const map = L.map("map", { zoomControl: true }).setView([20, 0], 2);
L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
  { attribution: "Tiles &copy; Esri", maxZoom: 16 }).addTo(map);
L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: 16, opacity: 0.9 }).addTo(map);

let layer = L.layerGroup().addTo(map);
let charts = {};
let current = null;

function pgvRadius(pgv) { return 4 + 9 * Math.sqrt(Math.max(pgv, 0) / 120); }

function fmt(x, d = 1) { return x == null ? "–" : (+x).toFixed(d); }

async function boot() {
  const idx = await fetch("data/index.json").then((r) => r.json());
  $("#index-meta").textContent =
    `${idx.events.length} events · updated ${idx.generated.slice(0, 16).replace("T", " ")} UTC`;
  const ul = $("#event-list");
  idx.events.forEach((e) => {
    const li = document.createElement("li");
    li.innerHTML =
      `<span class="ev-badge">${e.n_pulse}/${e.n}</span>` +
      `<div class="ev-name">${e.name || e.key}</div>` +
      `<div class="ev-sub">${e.mag_type} ${fmt(e.mag, 1)} · ` +
      `${(e.time || "").slice(0, 10)} · ${e.source}</div>`;
    li.onclick = () => selectEvent(e.key, li);
    ul.appendChild(li);
  });
  if (idx.events.length) selectEvent(idx.events[0].key, ul.firstChild);
}

let fitTarget = null;

async function selectEvent(key, li) {
  document.querySelectorAll("#event-list li").forEach((x) => x.classList.remove("active"));
  if (li) li.classList.add("active");
  current = await fetch(`data/events/${key}.json`).then((r) => r.json());
  drawMap(current);
  drawHead(current);
  drawCharts(current);
  $("#station-detail").innerHTML = '<span class="muted">Select a station on the map.</span>';
  requestAnimationFrame(refreshLayout);
}

function refreshLayout() {
  map.invalidateSize();
  if (fitTarget) map.fitBounds(fitTarget, { padding: [24, 24] });
  Object.values(charts).forEach((c) => c.resize());
}
addEventListener("resize", refreshLayout);

function drawMap(d) {
  layer.clearLayers();
  const ev = d.event, pts = [];

  if (ev.fault && ev.fault.polygon) {
    const poly = ev.fault.polygon.map(([lon, lat]) => [lat, lon]);
    L.polygon(poly, { color: FAULT, weight: 2, fillOpacity: 0.08 })
      .bindTooltip(`rupture plane · strike ${fmt(ev.fault.strike, 0)}° · ` +
        `L ${fmt(ev.fault.length_km, 0)} km`, { sticky: true })
      .addTo(layer);
    poly.forEach((p) => pts.push(p));
  }

  if (ev.lat != null) {
    L.marker([ev.lat, ev.lon], {
      icon: L.divIcon({ className: "", html: "★", iconSize: [22, 22],
        iconAnchor: [11, 11] }),
    }).bindPopup(`<b>${ev.name || "epicentre"}</b><br>${ev.mag_type} ${fmt(ev.mag, 1)}` +
      ` · depth ${fmt(ev.depth_km, 0)} km`).addTo(layer);
    pts.push([ev.lat, ev.lon]);
  }

  d.stations.forEach((s) => {
    if (s.lat == null) return;
    const m = L.circleMarker([s.lat, s.lon], {
      radius: pgvRadius(s.PGV),
      color: "#33404d", weight: 1,
      fillColor: s.is_pulse ? PULSE : "#ffffff",
      fillOpacity: s.is_pulse ? 0.85 : 0.9,
    }).addTo(layer);
    m.bindPopup(
      `<b>${s.code}</b> <span class="muted">${s.network || ""}</span><br>` +
      (s.is_pulse
        ? `pulse · T<sub>p</sub> ${fmt(s.Tp, 2)} s · PGV ${fmt(s.PGV, 0)} cm/s`
        : `no pulse · PGV ${fmt(s.PGV, 0)} cm/s`) +
      `<br>PI ${fmt(s.PI, 1)} · R<sub>epi</sub> ${fmt(s.repi_km, 0)} km` +
      (s.rrup_km != null ? ` · R<sub>rup</sub> ${fmt(s.rrup_km, 1)} km` : ""));
    m.on("click", () => stationDetail(s));
    if (s.is_pulse) addTick(s);
    pts.push([s.lat, s.lon]);
  });

  fitTarget = pts.length ? L.latLngBounds(pts).pad(0.15) : null;
  if (fitTarget) map.fitBounds(fitTarget, { padding: [24, 24] });
}

/* short segment showing the pulse (fault-normal) orientation */
function addTick(s) {
  const a = (s.angle_deg * Math.PI) / 180, km = 4;
  const dlat = (km * Math.cos(a)) / 111.3;
  const dlon = (km * Math.sin(a)) / (111.3 * Math.cos((s.lat * Math.PI) / 180));
  L.polyline([[s.lat - dlat, s.lon - dlon], [s.lat + dlat, s.lon + dlon]],
    { color: PULSE, weight: 2, opacity: 0.7 }).addTo(layer);
}

function drawHead(d) {
  const e = d.event, s = d.stats;
  $("#event-head").innerHTML =
    `<h3>${e.name || d.key}</h3>` +
    `<div class="kv">${e.mag_type} ${fmt(e.mag, 1)} · ${(e.time || "").slice(0, 16).replace("T", " ")} UTC` +
    ` · depth ${fmt(e.depth_km, 0)} km · ${e.source}</div>` +
    `<div class="stat-row">` +
    `<div class="stat"><b>${s.n_pulse}/${s.n}</b><span>pulse-like</span></div>` +
    `<div class="stat"><b>${fmt(s.Tp_median, 2)} s</b><span>median T<sub>p</sub></span></div>` +
    `<div class="stat"><b>${fmt(s.PGV_median, 0)}</b><span>median PGV cm/s</span></div>` +
    `</div><div class="kv">${d.pipeline}</div>`;
}

function scatterCfg(rows, yKey, yLabel) {
  const split = (v) => rows.filter((r) => r.is_pulse === v)
    .map((r) => ({ x: r.rrup_km ?? r.repi_km, y: r[yKey] }));
  return {
    type: "scatter",
    data: {
      datasets: [
        { label: "pulse", data: split(true), backgroundColor: PULSE, pointRadius: 4 },
        { label: "no pulse", data: split(false), backgroundColor: "#fff",
          borderColor: NOPULSE, borderWidth: 1, pointRadius: 3.5 },
      ],
    },
    options: {
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { type: "logarithmic", title: { display: true, text: "distance [km]" } },
        y: { type: "logarithmic", title: { display: true, text: yLabel } },
      },
      maintainAspectRatio: false,
    },
  };
}

function drawCharts(d) {
  Object.values(charts).forEach((c) => c.destroy());
  const rows = d.stats.scatter;
  charts.tp = new Chart($("#c-tp"), scatterCfg(rows, "Tp", "Tp [s]"));
  charts.pgv = new Chart($("#c-pgv"), scatterCfg(rows, "PGV", "PGV [cm/s]"));
  const b = d.stats.by_distance;
  charts.frac = new Chart($("#c-frac"), {
    type: "bar",
    data: {
      labels: b.map((x) => `${x.r_lo}–${x.r_hi}`),
      datasets: [{ data: b.map((x) => x.pulse_fraction), backgroundColor: PULSE }],
    },
    options: {
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (c) => {
          const x = b[c.dataIndex];
          return `${x.n_pulse}/${x.n} pulse · med Tp ${fmt(x.Tp_median, 1)} s`;
        } } } },
      animation: false,
      scales: { y: { min: 0, max: 1, title: { display: true, text: "fraction" } },
        x: { title: { display: true, text: "R_epi bin [km]" } } },
      maintainAspectRatio: false,
    },
  });
}

function stationDetail(s) {
  const g = (k, v) => `<span>${k}</span><span>${v}</span>`;
  $("#station-detail").innerHTML =
    `<h4>${s.code} <span class="muted">${s.network || ""}</span></h4>` +
    `<div class="sd-grid">` +
    g("verdict", s.is_pulse ? "<b style='color:#d62728'>pulse</b>" : "no pulse") +
    g("T<sub>p</sub>", `${fmt(s.Tp, 2)} s`) +
    g("PGV", `${fmt(s.PGV, 1)} cm/s`) +
    g("pulse indicator", fmt(s.PI, 2)) +
    g("orientation", `${fmt(s.angle_deg, 0)}°`) +
    g("R<sub>epi</sub>", `${fmt(s.repi_km, 1)} km`) +
    (s.rrup_km != null ? g("R<sub>rup</sub>", `${fmt(s.rrup_km, 1)} km`) : "") +
    (s.vs30 ? g("V<sub>s30</sub>", `${fmt(s.vs30, 0)} m/s`) : "") +
    g("QC", s.qc) +
    `</div><canvas id="spark"></canvas>`;
  if (s.pulse_trace) spark(s.pulse_trace);
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

boot().catch((e) => {
  $("#event-list").innerHTML =
    `<li class="muted">Could not load data/ — run <code>scripts/build_site_data.py</code> ` +
    `and serve this folder over http.<br>${e}</li>`;
});
