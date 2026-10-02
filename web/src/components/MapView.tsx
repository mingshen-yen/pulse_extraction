import L from "leaflet";
import { Fragment, useEffect, useMemo, useState } from "react";
import {
  CircleMarker, LayersControl, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip,
  useMap, useMapEvents,
} from "react-leaflet";

import type { EventSummary, EventView, Station } from "../api";
import { FAULT, PULSE, axis180, evDate, fmt, orientation, pgvRadius } from "../util";

const OSM_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

const star = (small: boolean) =>
  L.divIcon({
    className: small ? "epi epi-small" : "epi",
    html: "★",
    iconSize: small ? [16, 16] : [22, 22],
    iconAnchor: small ? [8, 8] : [11, 11],
  });
const STAR_SMALL = star(true);
const STAR = star(false);

/* Fit the view to `points` whenever `fitKey` changes, and on window resize. */
function Fit({ points, maxZoom, fitKey }: { points: [number, number][]; maxZoom: number; fitKey: string }) {
  const map = useMap();
  useEffect(() => {
    const fit = () => {
      map.invalidateSize();
      if (points.length)
        map.fitBounds(L.latLngBounds(points).pad(0.15), { padding: [24, 24], maxZoom });
      else map.setView([20, 0], 2);
    };
    fit();
    addEventListener("resize", fit);
    return () => removeEventListener("resize", fit);
  }, [fitKey, map]); // refit only when the view changes, not on every render
  return null;
}

/* Screen-constant double-ended bar through each pulse marker, along the pulse
   (fault-normal) polarisation axis; shown from zoom 5. */
function OrientationTicks({ stations }: { stations: Station[] }) {
  const map = useMap();
  const [, redraw] = useState(0);
  useMapEvents({ zoomend: () => redraw((n) => n + 1), viewreset: () => redraw((n) => n + 1) });
  if (map.getZoom() < 5) return null;
  return (
    <>
      {stations.map((s) => {
        const ori = orientation(s);
        if (!s.is_pulse || ori == null || s.lat == null || s.lon == null) return null;
        const a = (ori * Math.PI) / 180;
        const c = map.latLngToLayerPoint([s.lat, s.lon]);
        const half = pgvRadius(s.PGV) + 7; // px
        const dx = half * Math.sin(a),
          dy = -half * Math.cos(a);
        const p = [
          map.layerPointToLatLng([c.x - dx, c.y - dy]),
          map.layerPointToLatLng([c.x + dx, c.y + dy]),
        ];
        return (
          <Fragment key={s.code}>
            <Polyline positions={p} pathOptions={{ color: "#fff", weight: 4, opacity: 0.9, lineCap: "round" }} />
            <Polyline positions={p} pathOptions={{ color: "#1c2733", weight: 2, opacity: 0.95, lineCap: "round" }}>
              <Tooltip sticky>{`${s.code} · pulse orientation ${axis180(ori)}° from N`}</Tooltip>
            </Polyline>
          </Fragment>
        );
      })}
    </>
  );
}

function Overview({ events, onSelectEvent }: { events: EventSummary[]; onSelectEvent: (key: string) => void }) {
  return (
    <>
      {events.map((e) =>
        e.lat == null || e.lon == null ? null : (
          <Marker
            key={e.key}
            position={[e.lat, e.lon]}
            icon={STAR_SMALL}
            eventHandlers={{ click: () => onSelectEvent(e.key) }}
          >
            <Popup>
              <b>{e.name}</b>
              <br />
              {e.mag_type || "M"} {fmt(e.mag, 1)} · {evDate(e)}
              {e.n ? (
                <>
                  <br />
                  {e.n_pulse}/{e.n} pulse-like
                </>
              ) : null}
            </Popup>
          </Marker>
        ),
      )}
    </>
  );
}

function EventLayer({ view, onSelectStation }: { view: EventView; onSelectStation: (s: Station) => void }) {
  const ev = view.event;
  return (
    <>
      {ev.lat != null && ev.lon != null && (
        <Marker position={[ev.lat, ev.lon]} icon={STAR}>
          <Popup>
            <b>{ev.name}</b>
            <br />
            {ev.mag_type || "M"} {fmt(ev.mag, 1)} · depth {fmt(ev.depth_km, 0)} km
          </Popup>
        </Marker>
      )}
      {view.stations.map((s) =>
        s.lat == null || s.lon == null ? null : (
          <Fragment key={s.code}>
            <CircleMarker
              center={[s.lat, s.lon]}
              radius={pgvRadius(s.PGV)}
              pathOptions={{
                color: "#33404d",
                weight: 1,
                fillColor: s.is_pulse ? PULSE : "#ffffff",
                fillOpacity: s.is_pulse ? 0.85 : 0.9,
              }}
              eventHandlers={{ click: () => onSelectStation(s) }}
            >
              <Popup>
                <b>{s.code}</b> <span className="muted">{s.network || ""}</span>
                <br />
                {s.is_pulse ? (
                  <>
                    pulse · T<sub>p</sub> {fmt(s.Tp, 2)} s · PGV {fmt(s.PGV, 0)} cm/s
                  </>
                ) : (
                  <>no pulse · PGV {fmt(s.PGV, 0)} cm/s</>
                )}
                {s.rrup_km != null && (
                  <>
                    <br />R<sub>rup</sub> {fmt(s.rrup_km, 1)} km
                  </>
                )}
                {s.repi_km != null && (
                  <>
                    {" "}
                    · R<sub>epi</sub> {fmt(s.repi_km, 0)} km
                  </>
                )}
              </Popup>
            </CircleMarker>
            {s.fling && (
              <CircleMarker
                center={[s.lat, s.lon]}
                radius={pgvRadius(s.PGV) + 3}
                pathOptions={{ color: FAULT, weight: 1.5, fill: false }}
              >
                <Tooltip sticky>fling step</Tooltip>
              </CircleMarker>
            )}
          </Fragment>
        ),
      )}
      <OrientationTicks stations={view.stations} />
    </>
  );
}

export default function MapView(props: {
  events: EventSummary[];
  view: EventView | null;
  fitKey: string;
  onSelectEvent: (key: string) => void;
  onSelectStation: (s: Station) => void;
}) {
  const { events, view } = props;
  const points = useMemo<[number, number][]>(() => {
    if (!view) return events.filter((e) => e.lat != null && e.lon != null).map((e) => [e.lat!, e.lon!]);
    const pts: [number, number][] = [];
    if (view.event.lat != null && view.event.lon != null) pts.push([view.event.lat, view.event.lon]);
    for (const s of view.stations) if (s.lat != null && s.lon != null) pts.push([s.lat, s.lon]);
    return pts;
  }, [events, view]);
  // overview: whole catalog; event: epicentre + stations (an epicentre alone stays at 8)
  const maxZoom = !view || points.length === 1 ? 8 : 13;

  return (
    <MapContainer id="map" center={[20, 0]} zoom={2} zoomControl>
      <LayersControl position="topright" collapsed={false}>
        <LayersControl.BaseLayer checked name="Gray">
          <TileLayer
            url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
            attribution="Tiles &copy; Esri"
            maxZoom={16}
          />
        </LayersControl.BaseLayer>
        <LayersControl.BaseLayer name="OpenStreetMap">
          <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" attribution={OSM_ATTR} maxZoom={19} />
        </LayersControl.BaseLayer>
      </LayersControl>
      {view ? (
        <EventLayer view={view} onSelectStation={props.onSelectStation} />
      ) : (
        <Overview events={events} onSelectEvent={props.onSelectEvent} />
      )}
      <Fit points={points} maxZoom={maxZoom} fitKey={props.fitKey} />
    </MapContainer>
  );
}
