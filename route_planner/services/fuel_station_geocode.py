"""Build Pelias/ORS geocode queries from imported fuel station rows."""

from __future__ import annotations

from route_planner.models import FuelStation


def fuel_station_geocode_queries(station: FuelStation) -> list[str]:
    """
    Return search strings to try in order.

    OPIS ``address`` fields are often highway exits; appending city/state helps Pelias.
    A second query using the station name can improve matches when the address is vague.
    """
    city = station.city.strip()
    state = station.state.strip()
    address = station.address.strip()

    queries: list[str] = []
    if address:
        queries.append(", ".join(part for part in (address, city, state) if part))

    name = station.name.strip()
    if name:
        name_query = ", ".join(part for part in (name, city, state) if part)
        if name_query not in queries:
            queries.append(name_query)

    if not queries and city and state:
        queries.append(f"{city}, {state}")

    return queries
