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


def _xyz_index() -> Any:
    """Unit-sphere coordinates and populations of every place, as numpy arrays.

    Distance is computed vectorized over the whole dataset (225k rows is a few
    milliseconds), which keeps this one dependency-light array lookup instead of
    a spatial-index library.
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
    _index = (xyz, pop, places)
    return _index


def lookup(lat: float, lon: float) -> Optional[Place]:
    """Return the most significant place near (*lat*, *lon*), or None.

    "Most significant" = the largest population among the places within
    `_NEARBY_SLACK_KM` of the closest one; see the module docstring for why that
    beats plain nearest-city in both directions.
    """
    index = _xyz_index()
    if index is None:
        return None
    import numpy as np

    xyz, pop, places = index
    rlat, rlon = math.radians(lat), math.radians(lon)
    probe = np.array(
        [
            math.cos(rlat) * math.cos(rlon),
            math.cos(rlat) * math.sin(rlon),
            math.sin(rlat),
        ]
    )
    # Rank by the dot product with the probe -- a monotone stand-in for
    # great-circle distance -- so the whole-array pass is one matrix multiply.
    # The two arccos calls needed to turn a distance cutoff back into a dot
    # cutoff are O(1); doing the conversion the other way (arccos over all 225k
    # rows) is what made this 100 ms instead of 5 ms.
    dot = np.clip(xyz @ probe, -1.0, 1.0)
    nearest = int(np.argmax(dot))
    nearest_km = float(np.arccos(dot[nearest])) * _EARTH_R_KM
    if nearest_km > _CANDIDATE_KM:
        return None
    # The user's own places are exempt from the dominance rule below: they are
    # in the file precisely because no city on the map is what the photo is of.
    if places[nearest].custom:
        return places[nearest]
    cutoff_dot = math.cos((nearest_km + _NEARBY_SLACK_KM) / _EARTH_R_KM)
    near = np.flatnonzero(dot >= cutoff_dot)
    # Ties inside the cutoff are broken by distance, i.e. by *descending* dot.
    dist_km = -dot
    # The closest place is the default. A neighbour only takes the label off it
    # by being _DOMINANCE times bigger -- a city swallowing its own districts,
    # not a town swallowing the town next door. (A base population of 0 -- an
    # unpopulated entry -- is dominated by anything populated, which is how
    # Sekupang's photos end up saying Batam.)
    threshold = pop[nearest] * _DOMINANCE
    dominant = near[pop[near] > max(threshold, 0.0)]
    if dominant.size:
        best = dominant[int(np.lexsort((dist_km[dominant], -pop[dominant]))[0])]
        return places[int(best)]
    return places[nearest]


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
