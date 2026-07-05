"""Google encoded-polyline decoding (the format Strava's map fields use).

Implemented here (~25 lines) rather than adding a dependency: the format
is stable and documented — each coordinate is a delta from the previous
point, zigzag-signed, packed into base-63 chunks of 5 bits with 0x20 as
the continuation flag, at 1e-5 degree precision.
"""


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode to a list of (latitude, longitude) pairs."""
    coordinates: list[tuple[float, float]] = []
    index = 0
    latitude = 0
    longitude = 0
    while index < len(encoded):
        for coordinate in ("lat", "lon"):
            shift = 0
            result = 0
            while True:
                chunk = ord(encoded[index]) - 63
                index += 1
                result |= (chunk & 0x1F) << shift
                shift += 5
                if chunk < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if coordinate == "lat":
                latitude += delta
            else:
                longitude += delta
        coordinates.append((latitude * 1e-5, longitude * 1e-5))
    return coordinates


def first_point(encoded: str | None) -> tuple[float, float] | None:
    """The route's start coordinate, or None for empty/absent polylines."""
    if not encoded:
        return None
    points = decode_polyline(encoded)
    return points[0] if points else None
