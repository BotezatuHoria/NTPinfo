from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from typing import Tuple


@dataclass
class ServerLocation:
    """
    Represents the geographical location of a RIPE Atlas probe.

    Attributes:
        country_code (str): Two-letter ISO 3166-1 alpha-2 country code (e.g., 'US', 'DE') indicating
            the country where the probe is located
        coordinates (Tuple[float, float]): The latitude and longitude of the probe's physical location
    """
    country_code: str | None
    coordinates: Tuple[float, float] | None

    def __post_init__(self) -> None:
        if not isinstance(self.country_code, str | None):
            raise TypeError(f"country_code must be str, got {type(self.country_code).__name__}")
        if self.coordinates is not None:
            if not isinstance(self.coordinates[0], (float, int)):
                raise TypeError(f"coordinates must be float or int, got {type(self.coordinates[0]).__name__}")
            if not isinstance(self.coordinates[1], (float, int)):
                raise TypeError(f"coordinates must be float or int, got {type(self.coordinates[1]).__name__}")


@dataclass
class ProbeData:
    """
    Contains identifying and location information about a RIPE Atlas probe.

    Attributes:
        probe_id (str): The unique identifier of the probe
        probe_addr (Tuple[IPv4Address | None, IPv6Address | None]): The IPv4 and IPv6 addresses of the probe
        probe_location (ProbeLocation | None): Geographic location of the probe
    """
    probe_id: str | int
    probe_addr: Tuple[IPv4Address | None, IPv6Address | None]
    probe_location: ServerLocation | None

    def __post_init__(self) -> None:
        if not isinstance(self.probe_id, str | int):
            raise TypeError(f"probe_id must be str or int, got {type(self.probe_id).__name__}")
        if not isinstance(self.probe_addr[0], IPv4Address | None):
            raise TypeError(f"probe_addr must be IPv4 or None, got {type(self.probe_addr[1]).__name__}")
        if not isinstance(self.probe_addr[1], IPv6Address | None):
            raise TypeError(f"probe_addr must be IPv6 or None, got {type(self.probe_addr[1]).__name__}")
        if not isinstance(self.probe_location, ServerLocation | None):
            raise TypeError(f"probe_location must be ServerLocation, got {type(self.probe_location).__name__}")

