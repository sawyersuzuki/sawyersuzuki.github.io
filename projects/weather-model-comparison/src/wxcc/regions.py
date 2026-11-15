"""Regions: the nine census divisions (contiguous states + DC), a few
market-relevant states and state groups, and the whole of CONUS."""

from __future__ import annotations

# code -> (CPC/Census division number, name, state FIPS codes)
DIVISIONS: dict[str, tuple[int, str, tuple[str, ...]]] = {
    "NE": (1, "New England", ("09", "23", "25", "33", "44", "50")),
    "MA": (2, "Middle Atlantic", ("34", "36", "42")),
    "ENC": (3, "East North Central", ("17", "18", "26", "39", "55")),
    "WNC": (4, "West North Central", ("19", "20", "27", "29", "31", "38", "46")),
    "SA": (5, "South Atlantic", ("10", "11", "12", "13", "24", "37", "45", "51", "54")),
    "ESC": (6, "East South Central", ("01", "21", "28", "47")),
    "WSC": (7, "West South Central", ("05", "22", "40", "48")),
    "MTN": (8, "Mountain", ("04", "08", "16", "30", "32", "35", "49", "56")),
    "PAC": (9, "Pacific (contiguous)", ("06", "41", "53")),
}
# Sub-regions that matter for specific markets or events: code -> (name, state FIPS codes)
EXTRA_REGIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "TX": ("Texas", ("48",)),  # close to the ERCOT footprint
    "CA": ("California", ("06",)),  # close to the CAISO footprint
    "PNW": ("Pacific Northwest (WA, OR)", ("41", "53")),
    "NY": ("New York", ("36",)),  # the NYISO footprint
}
CONUS = "CONUS"
REGIONS: tuple[str, ...] = tuple(DIVISIONS) + tuple(EXTRA_REGIONS) + (CONUS,)
REGION_NAMES = (
    {code: name for code, (_, name, _) in DIVISIONS.items()}
    | {code: name for code, (name, _) in EXTRA_REGIONS.items()}
    | {CONUS: "Contiguous US"}
)
CPC_NUMBER = {code: num for code, (num, _, _) in DIVISIONS.items()}

STATE_TO_DIVISION: dict[str, str] = {
    fips: code for code, (_, _, states) in DIVISIONS.items() for fips in states
}
