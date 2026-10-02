import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchCatalogs,
  fetchEvent,
  fetchEvents,
  readFilters,
  writeFilters,
  type Catalog,
  type EventSummary,
  type EventView,
  type Filters,
  type Station,
} from "./api";
import MapView from "./components/MapView";
import Panel, { OverviewHead, type CrossLink } from "./components/Panel";
import Sidebar from "./components/Sidebar";
import { byNewest, findMatch } from "./util";

type Lists = Record<string, { events: EventSummary[]; nRecords: number }>;

export default function App() {
  const [catalogs, setCatalogs] = useState<Catalog[]>([]);
  const [lists, setLists] = useState<Lists>({});
  const [active, setActive] = useState("pipeline");
  const [filters, setFilters] = useState<Filters>(() =>
    readFilters(location.search),
  );
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<EventView | null>(null);
  const [station, setStation] = useState<Station | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overviewTick, setOverviewTick] = useState(0);

  useEffect(() => {
    fetchCatalogs().then(setCatalogs, (e) => setError(String(e)));
  }, []);

  // every catalog's (filtered) list, so the "also in" links work across catalogs
  useEffect(() => {
    if (!catalogs.length) return;
    let stale = false;
    setLoading(true);
    writeFilters(filters);
    Promise.all(
      catalogs.map((c) =>
        fetchEvents(c.id, filters).then((d) => [c.id, d] as const),
      ),
    )
      .then((pairs) => {
        if (stale) return;
        setLists(
          Object.fromEntries(
            pairs.map(([id, d]) => [
              id,
              { events: byNewest(d.events), nRecords: d.n_records },
            ]),
          ),
        );
        setView(null);
        setStation(null);
      })
      .catch((e) => !stale && setError(String(e)))
      .finally(() => !stale && setLoading(false));
    return () => {
      stale = true;
    };
  }, [catalogs, filters]);

  const selectEvent = useCallback(
    async (catId: string, key: string) => {
      const cat = catalogs.find((c) => c.id === catId);
      if (!cat) return;
      setActive(catId);
      setStation(null);
      try {
        setView(await fetchEvent(cat, key, filters));
      } catch (e) {
        setError(String(e));
      }
    },
    [catalogs, filters],
  );

  const showOverview = () => {
    setView(null);
    setStation(null);
    setOverviewTick((n) => n + 1);
  };

  const cat = catalogs.find((c) => c.id === active);
  const list = lists[active];
  const events = list?.events ?? [];
  const isFiltered = Object.keys(filters).length > 0;

  const links = useMemo<CrossLink[]>(() => {
    if (!view) return [];
    const yr = String(view.event.time || "").slice(0, 4);
    return catalogs.flatMap((c) => {
      if (c.id === active) return [];
      const m = findMatch(lists[c.id]?.events ?? [], view.event.name, yr);
      return m ? [{ catalog: c.id, label: c.label, key: m.key }] : [];
    });
  }, [view, catalogs, lists, active]);

  const filterNote = loading
    ? "loading…"
    : isFiltered && list
      ? `${list.nRecords} matching records`
      : "";
  const fitKey = view
    ? `event:${view.catalog}:${view.key}`
    : `overview:${active}:${JSON.stringify(filters)}:${overviewTick}:${events.length}`;

  return (
    <>
      <header>
        <h1>Near-fault Pulse Database v1</h1>
        <p>
          <b>Automatic pulse extraction pipeline </b> based on the
          Shahi&nbsp;&amp; Baker (2014) pulse classifier, fed by near-real-time
          waveforms from a strong-motion archive (GeoNet FDSN, ESM):
        </p>
        <p>
          <b>
            fetch&nbsp;&rarr; baseline correction &rarr; Arias window &rarr;
            classifier
          </b>
          .
        </p>
        <p className="muted">
          Each waveform in Pipeline results is processed end-to-end and mapped.
        </p>
        <a
          href="https://github.com/mingshen-yen/pulse_extraction"
          target="_blank"
          rel="noopener"
        >
          source&nbsp;&amp;&nbsp;validation&nbsp;&rarr;
        </a>
      </header>

      <main>
        <Sidebar
          catalogs={catalogs}
          active={active}
          events={events}
          selectedKey={view?.catalog === active ? view.key : null}
          filters={filters}
          filterNote={filterNote}
          error={error}
          onSource={(id) => {
            setActive(id);
            showOverview();
          }}
          onApply={setFilters}
          onOverview={showOverview}
          onSelectEvent={(key) => selectEvent(active, key)}
        />

        <section id="map-wrap">
          <MapView
            events={events}
            view={view}
            fitKey={fitKey}
            onSelectEvent={(key) => selectEvent(active, key)}
            onSelectStation={setStation}
          />
          <div id="legend">
            <span>
              <i className="dot pulse"></i> pulse
            </span>
            <span>
              <i className="dot nopulse"></i> no pulse
            </span>
            <span>
              <i className="bar"></i> marker size &prop; PGV
            </span>
            <span>
              <i className="tick"></i> pulse orientation
            </span>
            <span>
              <i className="ring"></i> fling step
            </span>
          </div>
        </section>

        <Panel
          head={
            cat && (
              <OverviewHead
                cat={cat}
                nEvents={events.length}
                nRecords={list?.nRecords ?? 0}
                nMapped={events.filter((e) => e.lat != null).length}
                filtered={isFiltered}
              />
            )
          }
          view={view}
          station={station}
          links={links}
          onLink={(l) => selectEvent(l.catalog, l.key)}
          onSelectStation={setStation}
        />
      </main>

      <footer className="muted">
        Event mechanism from USGS ComCat where available. Data © GeoNet / GNS
        Science (CC-BY 4.0), ESM / INGV (CC-BY). © 2026 Ming-Hsuan Yen. All
        rights reserved.
      </footer>
    </>
  );
}
