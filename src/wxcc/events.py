"""Historical extreme events offered in the dashboard's dropdown.

Windows are day labels (06Z-06Z) chosen around the peak of the population-
weighted signal in the ERA5 series for the listed region, not storm naming
dates. ``lookback_days`` is how many days of runs before the start to show.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Event:
    id: str
    name: str
    kind: str  # "cold" -> HDD, "heat" -> CDD
    start: str
    end: str
    region: str
    note: str


EVENTS: list[Event] = [
    Event("fern-2026", "Winter Storm Fern (Jan 2026)", "cold", "2026-01-23", "2026-01-27", "CONUS",
          "Arctic outbreak with widespread production freeze-offs; EIA reported a record 360 Bcf "
          "storage withdrawal for the week ending 30 January 2026."),
    Event("heat-2025", "Eastern US heat dome (Jun 2025)", "heat", "2025-06-22", "2025-06-25", "MA",
          "Early-season heat dome over the Midwest and Northeast; PJM and NYISO issued hot-weather alerts."),
    Event("cold-2025", "Arctic outbreak (Jan 2025)", "cold", "2025-01-19", "2025-01-23", "CONUS",
          "Cold air mass reaching the Gulf Coast, with rare snow from Houston to the Florida Panhandle."),
    Event("cold-2024", "Arctic outbreak (Jan 2024)", "cold", "2024-01-13", "2024-01-17", "CONUS",
          "Winter storms Gerri and Heather; record US gas demand and large freeze-offs in mid-January."),
    Event("elliott-2022", "Winter Storm Elliott (Dec 2022)", "cold", "2022-12-22", "2022-12-26", "CONUS",
          "Rapid Arctic front before Christmas; generator outages and load shedding in the Southeast "
          "(TVA, Duke) and emergency conditions in PJM."),
    Event("heatdome-2021", "Pacific Northwest heat dome (Jun 2021)", "heat", "2021-06-26", "2021-06-29", "PNW",
          "All-time records in Portland and Seattle; Lytton, BC reached 49.6 C on 29 June."),
    Event("uri-2021", "Winter Storm Uri (Feb 2021)", "cold", "2021-02-13", "2021-02-17", "TX",
          "ERCOT load shed and multi-day outages across Texas; record gas price spikes in the mid-continent."),
]


def as_dicts() -> list[dict]:
    return [asdict(e) for e in EVENTS]
