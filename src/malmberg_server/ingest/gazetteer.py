"""The offline place-name dataset behind reverse_geocode, and how it picks.

Two things were wrong with plain nearest-city lookup over `reverse_geocoder`'s
bundled list, and they pull in opposite directions:

1. **The list is too sparse.** It is GeoNames' cities1000 filtered down
   further, and the gaps are not where you would guess: Batam -- an Indonesian
   city of 1.3 million people, 25 km across the strait from Singapore -- is
   simply absent. Nearest-city then labels every photo taken on Batam
   "Singapore, SG", along with the whole Riau archipelago. We ship GeoNames
   cities500 instead (every populated place down to ~500 people, 225k rows,
   gzipped in `malmberg_server/data/`), which has Batam and is denser
   everywhere else too.

2. **A dense list makes nearest-city too literal.** The nearest populated place
   to a photo taken downtown in Singapore is a new town like Ang Mo Kio, not
   Singapore -- so a denser dataset alone shatters "Singapore" into districts
   and makes the by-place tree useless.

So the lookup is population-aware. The closest place wins by default, but a
nearby one takes the label off it if it is `_DOMINANCE` times bigger -- a city
swallowing its own districts, never a town swallowing the town next door. Ang
Mo Kio (174k, 7 km from a 3.5M Singapore) yields; Oxelosund (11k, 11 km from a
merely 30k Nykoping) does not; and Nongsa on Batam is 29 km from Singapore, so
Singapore is not even a candidate -- which is the whole point.

Everything here is offline: no lookup ever leaves the machine. A user CSV
(`<fs_root>/geocode-extra.csv`, same columns) is merged on top if present, for
the places no public gazetteer will ever have -- a cabin, a family farm,
"Grandma's house".

Place names are the real ones, accents and all (the dataset is UTF-8): a photo
taken in Sweden should say Oxelosund with the o-umlaut, not a transliteration.
The dataset is a gzipped blob rather than source, so this costs the codebase no
non-ASCII characters.

Data: GeoNames (https://geonames.org), CC BY 4.0.
"""

from __future__ import annotations

import csv
import gzip
import io
import math
from pathlib import Path
from typing import Any, NamedTuple, Optional

from malmberg_core.logging import get_logger

_log = get_logger(__name__)

GAZETTEER_VERSION = 2
"""Bumped whenever the dataset or the picking rule changes.

Stored per item as MediaMetadata.geo_version; the background sweep in
ingest.regeocode recomputes `place` for every item behind the current version
from its stored lat/lon, so a gazetteer fix reaches the existing library on its
own -- no re-ingest, no manual step, no photo files touched.
"""

EXTRA_CSV_NAME = "geocode-extra.csv"
"""User-supplied additions, read from <fs_root>/geocode-extra.csv. Same columns
as the bundled dataset: lat,lon,name,admin1,cc,population."""

_NEARBY_SLACK_KM = 12.0
"""How much farther than the closest place we will even look for a bigger one.

Batam's Nongsa is 29 km from central Singapore, so Singapore is never in the
running for a photo taken there -- which is the whole point of this change.
"""

_DOMINANCE = 10.0
"""How many times bigger a neighbour must be to take a photo's label.

Distance alone cannot tell "a district of a city" from "a town in its own
right", but relative size can. Ang Mo Kio (174k) is a new town *inside*
Singapore (3.5M, 20x bigger, 7 km away), so the photo should say Singapore.
Oxelosund (11k) is a town in its own right next to Nykoping (30k, only 3x
bigger, 11 km away), so the photo should keep saying Oxelosund -- being near
somewhere slightly larger must not erase you. Only a genuinely dominant
neighbour wins.
"""

_CANDIDATE_KM = 60.0
"""Radius searched at all. Beyond this a photo is somewhere with no populated
place nearby (mid-ocean, deep wilderness) and gets no label at all, rather than
a misleading one 200 km away."""

_EARTH_R_KM = 6371.0


class Place(NamedTuple):
    """One row of the gazetteer."""

    lat: float
    lon: float
    name: str
    admin1: str
    cc: str
    population: int
    custom: bool = False
    """True for rows from the user's extras file. They are exempt from the
    dominance rule: if the user says a spot on the map is Grandma's house, a
    photo taken there says Grandma's house, and no city outvotes it."""

    @property
    def label(self) -> str:
        """ "City, Region, CC" -- parts that are missing are dropped."""
        parts = [p for p in (self.name, self.admin1, self.cc) if p]
        return ", ".join(parts)


_places: Optional[list[Place]] = None
_failed = False
"""Set once loading has failed, so a broken dataset is not retried per photo."""

_extra_csv: Optional[Path] = None
_index: Any = None
"""(unit-sphere xyz array, population array, places) -- built once, on demand."""


def configure(fs_root: Optional[Path]) -> None:
    """Point the gazetteer at *fs_root* (for the optional user CSV).

    Call once at server startup, before the first lookup. Drops any loaded
    dataset so a later call takes effect.
    """
    global _extra_csv, _places, _index, _failed
    _extra_csv = (fs_root / EXTRA_CSV_NAME) if fs_root is not None else None
    _places = None
    _index = None
    _failed = False


def _parse_rows(text: str, source: str, *, custom: bool = False) -> list[Place]:
    """Parse gazetteer CSV *text*. Bad rows are skipped, never fatal: a typo in
    the user's extras file must not take reverse-geocoding down for the whole
    library."""
    out: list[Place] = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out.append(
                Place(
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    name=(row.get("name") or "").strip(),
                    admin1=(row.get("admin1") or "").strip(),
                    cc=(row.get("cc") or "").strip(),
                    population=int(float(row.get("population") or 0)),
                    custom=custom,
                )
            )
        except (TypeError, ValueError, KeyError):
            _log.warning("Gazetteer: skipping malformed row in %s: %r", source, row)
    return out


def _load() -> list[Place]:
    """Load the bundled dataset plus the user's extras. Cached; [] on failure."""
    global _places, _failed
    if _places is not None:
        return _places
    if _failed:
        return []
    try:
        from importlib.resources import files

        blob = files("malmberg_server.data").joinpath("cities500.csv.gz").read_bytes()
        places = _parse_rows(gzip.decompress(blob).decode("utf8"), "cities500")
    except Exception:
        _log.error(
            "Could not load the gazetteer; places will not be populated",
            exc_info=True,
        )
        _failed = True
        return []
    if _extra_csv is not None and _extra_csv.is_file():
        try:
            extra = _parse_rows(
                _extra_csv.read_text(encoding="utf8"), str(_extra_csv), custom=True
            )
            _log.info(
                "Gazetteer: merged %d extra place(s) from %s", len(extra), _extra_csv
            )
            places = places + extra
        except OSError:
            _log.warning("Could not read %s; ignoring it", _extra_csv, exc_info=True)
    _log.info("Gazetteer ready: %d places (version %d)", len(places), GAZETTEER_VERSION)
    _places = places
    return _places


def _build_index() -> Any:
    """Build the spatial index: unit-sphere coords, populations, and a grid.

    Scanning all 225k rows per photo is ~9 ms idle, which sounds fine until the
    server re-geocodes 12,760 photos while the face worker and thumbnail warmer
    are already saturating a 4-core NAS -- then it is 3 billion distance
    computations fighting for cores, and the sweep crawls.

    So places are bucketed into 1-degree lat/lon cells. A lookup only measures
    the handful of cells that could hold something within `_CANDIDATE_KM`,
    which is a few hundred candidates instead of 225k.
    """
    global _index
    if _index is not None:
        return _index
    places = _load()
    if not places:
        return None
    try:
        import numpy as np
    except ImportError:
        _log.warning(
            "numpy unavailable; photo places will not be populated "
            "(install the 'geocode' extra on the server)"
        )
        return None
    lat = np.radians(np.fromiter((p.lat for p in places), float, len(places)))
    lon = np.radians(np.fromiter((p.lon for p in places), float, len(places)))
    pop = np.fromiter((p.population for p in places), float, len(places))
    xyz = np.stack(
        [np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], axis=1
    )
    cells: dict[tuple[int, int], list[int]] = {}
    for i, place in enumerate(places):
        cells.setdefault(_cell(place.lat, place.lon), []).append(i)
    _index = (xyz, pop, places, cells)
    _log.info("Gazetteer index built: %d places in %d cells", len(places), len(cells))
    return _index


def _cell(lat: float, lon: float) -> tuple[int, int]:
    """The 1-degree grid cell a coordinate falls in."""
    return (math.floor(lat), math.floor(lon))


def _candidate_ids(cells: dict, lat: float, lon: float) -> list[int]:
    """Indices of every place in the cells that could hold a hit near (lat, lon).

    The latitude span is fixed, but a degree of longitude shrinks towards the
    poles -- so the longitude span is widened by 1/cos(lat), and near the poles
    (or across the +/-180 seam) we simply take every longitude rather than get
    the wraparound subtly wrong.
    """
    span_lat = int(math.ceil(_CANDIDATE_KM / 111.0)) + 1
    cos_lat = math.cos(math.radians(lat))
    if cos_lat < 0.05:
        lon_cells = range(-180, 180)
    else:
        span_lon = int(math.ceil(_CANDIDATE_KM / (111.0 * cos_lat))) + 1
        lon_cells = range(-span_lon, span_lon + 1)
    base_lat, base_lon = _cell(lat, lon)
    out: list[int] = []
    for dlat in range(-span_lat, span_lat + 1):
        for dlon in lon_cells:
            # Wrap longitude at the antimeridian; clamp latitude (there is no
            # cell past the pole).
            clat = base_lat + dlat
            if clat < -90 or clat > 89:
                continue
            clon = base_lon + dlon if cos_lat >= 0.05 else dlon
            clon = ((clon + 180) % 360) - 180
            hit = cells.get((clat, clon))
            if hit:
                out.extend(hit)
    return out


def lookup(lat: float, lon: float) -> Optional[Place]:
    """Return the most significant place near (*lat*, *lon*), or None.

    The closest place wins by default; a neighbour within `_NEARBY_SLACK_KM`
    takes the label only by being `_DOMINANCE` times bigger. See the module
    docstring for why that beats plain nearest-city in both directions.
    """
    index = _build_index()
    if index is None:
        return None
    import numpy as np

    xyz, pop, places, cells = index
    ids = _candidate_ids(cells, lat, lon)
    if not ids:
        return None
    idx = np.fromiter(ids, int, len(ids))
    rlat, rlon = math.radians(lat), math.radians(lon)
    probe = np.array(
        [
            math.cos(rlat) * math.cos(rlon),
            math.cos(rlat) * math.sin(rlon),
            math.sin(rlat),
        ]
    )
    # Rank by the dot product with the probe -- a monotone stand-in for
    # great-circle distance -- over the candidate cells only.
    dot = np.clip(xyz[idx] @ probe, -1.0, 1.0)
    cand_pop = pop[idx]

    nearest = int(np.argmax(dot))
    nearest_km = float(np.arccos(dot[nearest])) * _EARTH_R_KM
    if nearest_km > _CANDIDATE_KM:
        return None
    # The user's own places are exempt from the dominance rule below: they are
    # in the file precisely because no city on the map is what the photo is of.
    if places[int(idx[nearest])].custom:
        return places[int(idx[nearest])]

    cutoff_dot = math.cos((nearest_km + _NEARBY_SLACK_KM) / _EARTH_R_KM)
    near = np.flatnonzero(dot >= cutoff_dot)
    # The closest place is the default. A neighbour only takes the label off it
    # by being _DOMINANCE times bigger -- a city swallowing its own districts,
    # not a town swallowing the town next door. (A base population of 0 -- an
    # unpopulated entry -- is dominated by anything populated, which is how
    # Sekupang's photos end up saying Batam.)
    threshold = cand_pop[nearest] * _DOMINANCE
    dominant = near[cand_pop[near] > max(float(threshold), 0.0)]
    if dominant.size:
        # Ties inside the cutoff are broken by distance, i.e. by descending dot.
        best = dominant[int(np.lexsort((-dot[dominant], -cand_pop[dominant]))[0])]
        return places[int(idx[best])]
    return places[int(idx[nearest])]


def reverse_geocode(lat: float | None, lon: float | None) -> str | None:
    """Best-effort offline reverse geocode of (*lat*, *lon*) to a place label.

    Returns "City, Region, CC", or None if coordinates are absent, the dataset
    or numpy is unavailable, or nothing populated is within `_CANDIDATE_KM`.
    Never raises and never makes a network request -- ingestion must not be able
    to fail here.
    """
    if lat is None or lon is None:
        return None
    try:
        place = lookup(lat, lon)
    except Exception:
        _log.warning("reverse_geocode failed for (%s, %s)", lat, lon, exc_info=True)
        return None
    return place.label if place is not None and place.label else None
