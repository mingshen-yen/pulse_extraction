"""Resolve an instrument response for a channel, with fallbacks.

``resolve_response`` tries, in order:

 1. ``file``               -- a StationXML the caller supplied
 2. ``cache``              -- ``data/stationxml/<net>.<sta>.xml`` from a past run
 3. ``fdsn``              -- the primary FDSN client, response for the time window
 4. ``fdsn-other-epoch``  -- the same client, response for *any* epoch (warn)
 5. ``fdsn-routed``       -- the IRIS federator / EIDA routing / a list of nodes
 6. ``nominal``           -- a caller-supplied scalar sensitivity (counts per
                             m/s**2); flat-response deconvolution (warn)
 7. ``assumed-physical``  -- no response anywhere, but the sample values look
                             like physical units already -- pass through (warn)
 8. ``none``              -- nothing worked; the record cannot be trusted (fail)

Successful FDSN / routed lookups are written back to the cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np

DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "data" / "stationxml"
_ROUTERS = ("iris-federator", "eida-routing")
_FALLBACK_NODES = ("IRIS", "ORFEUS", "GFZ", "RESIF")

# peak-amplitude window for "already physical acceleration" -- wide enough to
# cover both m/s**2 (~<30) and cm/s**2 / gal (~<3000) strong-motion records
_PHYS_LO, _PHYS_HI = 1e-4, 5000.0


@dataclass
class ResponseInfo:
    source: str                       # one of the tags above
    level: str                        # "ok" | "warn" | "fail"
    inventory: object = None          # obspy Inventory for real deconvolution
    scalar_sensitivity: Optional[float] = None   # counts per m/s**2 (nominal)
    messages: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.level != "fail"

    def to_dict(self):
        return {"source": self.source, "level": self.level,
                "scalar_sensitivity": self.scalar_sensitivity,
                "messages": list(self.messages)}


def _cache_path(cache_dir, net, sta):
    return Path(cache_dir) / f"{net}.{sta}.xml"


def _covers(inv, net, sta, loc, cha, t0, t1) -> bool:
    try:
        sub = inv.select(network=net, station=sta, location=loc, channel=cha,
                         starttime=t0, endtime=t1)
        for n in sub:
            for s in n:
                for c in s:
                    if c.response is not None:
                        return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _has_any_response(inv, net, sta, cha) -> bool:
    try:
        sub = inv.select(network=net, station=sta, channel=cha)
        for n in sub:
            for s in n:
                for c in s:
                    if c.response is not None:
                        return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _write_cache(inv, cache_dir, net, sta, msgs):
    try:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        p = _cache_path(cache_dir, net, sta)
        # merge with any existing cached epochs
        if p.exists():
            from obspy import read_inventory
            try:
                inv = read_inventory(str(p)) + inv
            except Exception:  # noqa: BLE001
                pass
        inv.write(str(p), format="STATIONXML")
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"could not write cache: {exc}")


def _looks_physical(data_sample) -> Optional[bool]:
    """True if amplitudes look like m/s**2, False if they look like raw counts,
    None if inconclusive."""
    if data_sample is None:
        return None
    x = np.asarray(data_sample, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return None
    peak = float(np.max(np.abs(x)))
    if peak == 0:
        return None
    frac_int = float(np.mean(np.abs(x - np.round(x)) < 1e-6))
    # nothing physical (m/s**2 or gal) peaks that high
    if peak > 5e4:
        return False
    # integer-valued *and* large -> raw digitiser counts
    if frac_int > 0.98 and peak > 2000:
        return False
    if _PHYS_LO <= peak <= _PHYS_HI:
        return True
    return None


def resolve_response(net, sta, loc, cha, starttime, endtime, *,
                     stationxml: Optional[str] = None,
                     client=None,
                     cache_dir=DEFAULT_CACHE,
                     routing: bool = True,
                     fallback_nodes=_FALLBACK_NODES,
                     nominal_sensitivity=None,
                     data_sample=None) -> ResponseInfo:
    """See module docstring.  ``client`` is an obspy FDSN ``Client`` (or ``None``
    to skip step 3/4).  ``nominal_sensitivity`` is a float (counts per m/s**2)
    or a dict keyed by ``"NET.STA.CHA"`` / ``"NET.STA"``."""
    from obspy import read_inventory

    msgs: List[str] = []
    t0, t1 = starttime, endtime

    # 1. explicit file -----------------------------------------------------
    if stationxml:
        p = Path(stationxml)
        if p.is_file():
            inv = read_inventory(str(p))
            return ResponseInfo("file", "ok", inventory=inv,
                                messages=[f"from {p.name}"])
        msgs.append(f"stationxml {stationxml} not found")

    # 2. cache -----------------------------------------------------------------
    cp = _cache_path(cache_dir, net, sta)
    cached = None
    if cp.is_file():
        try:
            cached = read_inventory(str(cp))
            if _covers(cached, net, sta, loc, cha, t0, t1):
                return ResponseInfo("cache", "ok", inventory=cached,
                                    messages=[f"from {cp.name}"])
        except Exception as exc:  # noqa: BLE001
            msgs.append(f"cache unreadable: {exc}")

    # 3/4. primary FDSN client ----------------------------------------------
    if client is not None:
        try:
            inv = client.get_stations(network=net, station=sta, location=loc,
                                      channel=cha, starttime=t0, endtime=t1,
                                      level="response")
            if _covers(inv, net, sta, loc, cha, t0, t1):
                _write_cache(inv, cache_dir, net, sta, msgs)
                return ResponseInfo("fdsn", "ok", inventory=inv, messages=msgs)
        except Exception as exc:  # noqa: BLE001
            msgs.append(f"fdsn window lookup failed: {exc}")
        try:
            inv = client.get_stations(network=net, station=sta, location=loc,
                                      channel=cha, level="response")
            if _has_any_response(inv, net, sta, cha):
                _write_cache(inv, cache_dir, net, sta, msgs)
                return ResponseInfo(
                    "fdsn-other-epoch", "warn", inventory=inv,
                    messages=msgs + ["response is from a different epoch"])
        except Exception as exc:  # noqa: BLE001
            msgs.append(f"fdsn any-epoch lookup failed: {exc}")

    # 5. routing / other nodes ----------------------------------------------
    if routing:
        from obspy.clients.fdsn import Client
        from obspy.clients.fdsn.routing.routing_client import RoutingClient
        tried = []
        for r in _ROUTERS:
            tried.append(("router", r))
        for node in fallback_nodes:
            tried.append(("node", node))
        for kind, name in tried:
            try:
                c = (RoutingClient(name) if kind == "router" else Client(name))
                inv = c.get_stations(network=net, station=sta, location=loc,
                                     channel=cha, starttime=t0, endtime=t1,
                                     level="response")
                if _covers(inv, net, sta, loc, cha, t0, t1) or \
                   _has_any_response(inv, net, sta, cha):
                    _write_cache(inv, cache_dir, net, sta, msgs)
                    return ResponseInfo(
                        "fdsn-routed", "warn", inventory=inv,
                        messages=msgs + [f"response via {name}"])
            except Exception as exc:  # noqa: BLE001
                msgs.append(f"{name} failed: {exc}")

    # 4b. stale cache (any epoch) as a last metadata resort ----------------
    if cached is not None and _has_any_response(cached, net, sta, cha):
        return ResponseInfo("fdsn-other-epoch", "warn", inventory=cached,
                            messages=msgs + ["fell back to cached other-epoch response"])

    # 6. nominal scalar sensitivity ---------------------------------------------
    sens = None
    if isinstance(nominal_sensitivity, dict):
        sens = (nominal_sensitivity.get(f"{net}.{sta}.{cha}")
                or nominal_sensitivity.get(f"{net}.{sta}")
                or nominal_sensitivity.get("*"))
    elif nominal_sensitivity is not None:
        sens = float(nominal_sensitivity)
    if sens:
        return ResponseInfo(
            "nominal", "warn", scalar_sensitivity=float(sens),
            messages=msgs + [f"nominal sensitivity {sens:g} counts/(m/s**2); "
                             "amplitudes are approximate"])

    # 7. data already in physical units? -----------------------------------
    phys = _looks_physical(data_sample)
    if phys is True:
        return ResponseInfo(
            "assumed-physical", "warn",
            messages=msgs + ["no response found; sample amplitudes look "
                             "physical -- passed through without deconvolution"])

    # 8. give up -----------------------------------------------------------
    reason = ("data looks like raw counts and no response is available"
              if phys is False else
              "no response available and units could not be inferred")
    return ResponseInfo("none", "fail", messages=msgs + [reason])


def apply_response(tr, info: ResponseInfo, *,
                   pre_filt=(0.02, 0.05, 40.0, 50.0), water_level=60.0):
    """Convert ``tr`` in place to acceleration in **cm/s**2** per ``info``.

    Raises ``ValueError`` if ``info.source == "none"``.
    """
    M_S2_TO_CM_S2 = 100.0
    if info.source == "none":
        raise ValueError("no usable instrument response: "
                         + "; ".join(info.messages))
    if info.inventory is not None:
        tr.remove_response(inventory=info.inventory, output="ACC",
                           pre_filt=pre_filt, water_level=water_level,
                           taper=True, taper_fraction=0.05)
        tr.data = tr.data * M_S2_TO_CM_S2
    elif info.scalar_sensitivity:
        tr.detrend("demean")
        tr.data = (tr.data / info.scalar_sensitivity) * M_S2_TO_CM_S2
    else:
        # assumed-physical: units unverified, take the samples as-is
        tr.detrend("demean")
    return tr
