from typing import TypeVar
from typing import Optional

from server.app.utils.location_resolver import get_coordinates_for_ip
from server.app.utils.calculations import calculate_haversine_distance
from server.app.models.CustomError import InputError
from server.app.utils.load_config_data import get_ripe_number_of_probes_per_measurement
from server.app.utils.ip_utils import get_ip_network_details, get_prefix_from_ip, get_ip_family
from ripe.atlas.cousteau import ProbeRequest

T = TypeVar('T', int, float)  # float or int


def get_probes(client_ip: str, ip_family_of_ntp_server: int,
               probes_requested: int = get_ripe_number_of_probes_per_measurement()) -> list[dict]:
    """
    This method handles all cases regarding what probes we should send.
    This method assumes all inputs are either valid or None. (If there is a typo in the input, the measurement
    may be affected)
    It will try to return the best probes near the client.

    Args:
        client_ip (str): The IP address of the client.
        ip_family_of_ntp_server (int): The IP family of the NTP server. (4 or 6)
        probes_requested (int): The total number of probes that we will request.

    Returns:
        list[dict]: The list of probes that we will use for the measurement.

    Raises:
        InputError: If the client IP address is invalid
    """
    # get the details. (this will take around 150-200ms)
    ip_family: int = get_ip_family(client_ip)
    ip_asn, ip_country, ip_area = get_ip_network_details(client_ip)
    ip_prefix = None
    # the prefix is relevant if and only if the client has the same IP type as the NTP server.
    # Otherwise, we won't "find probes with the same prefix as the client that can perform NTP measurements for that server"

    # If we do not have this check, "get available" methods that involves prefix will fail
    if ip_family == ip_family_of_ntp_server:
        ip_prefix = get_prefix_from_ip(client_ip)

    # settings:
    probes: list[dict] = []
    current_probes_set: set[int] = set()
    # Try to see if we have probes with the same ASN and prefix OR same ASN and same country. They have the highest priority.
    probes_requested, current_probes_set = (
        get_best_probes_with_multiple_attributes(client_ip=client_ip, current_probes_set=current_probes_set,
                                                 ip_asn=ip_asn, ip_prefix=ip_prefix,
                                                 ip_country=ip_country, ip_family=ip_family_of_ntp_server,
                                                 probes_requested=probes_requested))

    if probes_requested <= 0:
        # add the current IDs of the probes
        probes.append(get_probes_by_ids(list(current_probes_set)))
        return probes

    # if we still need more probes or if the method above failed, continue trying with filters by a single attributes.
    probes_requested, current_probes_set = (
        get_best_probes_matched_by_single_attribute(client_ip=client_ip, current_probes_set=current_probes_set,
                                                    ip_asn=ip_asn, ip_prefix=ip_prefix,
                                                    ip_country=ip_country, ip_family=ip_family_of_ntp_server,
                                                    probes_requested=probes_requested))
    # add the IDs of the probes
    if len(current_probes_set) > 0:
        probes.append(get_probes_by_ids(list(current_probes_set)))
    # if we still need to add probes
    # the last resort is to use probes from the same area or random if it is not available
    if probes_requested > 0:
        if ip_area is not None:
            probes.append(get_area_probes(ip_area, probes_requested))
        else:
            probes.append(get_random_probes(probes_requested))
    return probes


def get_best_probes_with_multiple_attributes(client_ip: str, current_probes_set: set[int], ip_asn: Optional[str],
                                             ip_prefix: Optional[str], ip_country: Optional[str],
                                             ip_family: int,
                                             probes_requested: int = get_ripe_number_of_probes_per_measurement()) -> \
        tuple[int, set[int]]:
    """
    This method tries to get probes that has the same ASN and prefix OR the same ASN and country and subtract them
    from the probes_requested. These probes have the highest priority as they have multiple attributes as the client IP
    (same ASN and same prefix OR same ASN or same country)

    Args:
        client_ip (str): The IP address of the client.
        current_probes_set (set[int]): The set of probes that we will use for the measurement. (to be sure that we do not include duplicates)
        ip_asn (Optional[str]): The ASN of the NTP server IP address.
        ip_prefix (Optional[str]): The prefix of the NTP server IP address.
        ip_country (Optional[str]): The country of the NTP server IP address.
        ip_family (int): The family of the NTP server IP address. (4 or 6)
        probes_requested (int): The number of probes that we still need to request.

    Returns:
        tuple[int, set[int]]: The updated number of probes that we still need to find after this method call.
                               a list of the IDs of the probes that we found until now.

    Raises:
        InputError: If the input is invalid or probes_requested is negative.
    """
    if probes_requested < 0:
        raise InputError("Probe requested cannot be negative")

    ip_type = "ipv" + str(ip_family)
    # see if we can get enough probes from probes with the same ASN and same prefix:
    if ip_asn is not None and ip_prefix is not None:
        ids = get_available_probes_asn_and_prefix(client_ip, ip_asn, ip_prefix, ip_type)
        probes_requested, current_probes_set = consume_probes(probes_requested, current_probes_set, ids)
        if probes_requested <= 0:
            return 0, set(current_probes_set)

    # try with the probes from the same ASN and country
    if ip_asn is not None and ip_country is not None:
        ids = get_available_probes_asn_and_country(client_ip, ip_asn, ip_country, ip_type)
        probes_requested, current_probes_set = consume_probes(probes_requested, current_probes_set, ids)

    return probes_requested, set(current_probes_set)


def get_best_probes_matched_by_single_attribute(client_ip: str, current_probes_set: set[int], ip_asn: Optional[str],
                                                ip_prefix:
                                                Optional[str], ip_country: Optional[str], ip_family: int,
                                                probes_requested: int = get_ripe_number_of_probes_per_measurement()) \
        -> tuple[int, set[int]]:
    """
    This method is responsible for getting the best probes that has a match by a single attribute in this order: ASN, prefix, country.
    As soon as we have enough probes we return.

    Args:
        client_ip (str): The IP address of the client.
        current_probes_set (set[int]): The set of probes that we will use for the measurement. (to be sure that we do not include duplicates)
        ip_asn (int): The ASN of the NTP server IP address.
        ip_prefix (str): The prefix of the NTP server IP address.
        ip_country (str): The country of the NTP server IP address.
        ip_family (int): The family of the NTP server IP address. (4 or 6)
        probes_requested (int): The number of probes that we still need to request.

    Returns:
        tuple[int, set[int]]: - The updated number of probes that we still need to find after this method call.
                              - The set of probe types and the respective number of probes.

    Raises:
        InputError: If the NTP server IP is invalid or if the probes_requested is negative.
    """
    if probes_requested < 0:
        raise InputError("Probe requested cannot be negative")
    ip_type = "ipv" + str(ip_family)
    ids: list[int]
    # try ASN
    if ip_asn is not None:
        ids = get_available_probes_asn(client_ip, ip_asn, ip_type)
        probes_requested, current_probes_set = consume_probes(probes_requested, current_probes_set, ids)
        if probes_requested <= 0:
            return 0, current_probes_set

    # try prefix
    if ip_prefix is not None:
        ids = get_available_probes_prefix(client_ip, ip_prefix, ip_type)
        probes_requested, current_probes_set = consume_probes(probes_requested, current_probes_set, ids)
        if probes_requested <= 0:
            return 0, current_probes_set

    # try country
    if ip_country is not None:
        ids = get_available_probes_country(client_ip, ip_country, ip_type)
        probes_requested, probes_to_use = consume_probes(probes_requested, current_probes_set, ids)
        if probes_requested <= 0:
            return 0, current_probes_set

    # if we still need to find probes
    return probes_requested, current_probes_set


def get_probes_by_ids(probe_ids: list[int]) -> dict:
    """
        This method selects probes by their IDs.

        Args:
            probe_ids (list[int]): The IDs of the probes.

        Returns:
            dict: the selected probes

        Raises:
            InputError: If the input is invalid
        """
    if len(probe_ids) == 0:
        raise InputError("probe_ids cannot be empty")
    list_str = [str(p) for p in probe_ids]
    formatted_list = ','.join(list_str)
    # print(formatted_list)
    probes = {
        "type": "probes",
        "value": formatted_list,
        "requested": len(probe_ids)
    }
    return probes


def get_asn_probes(ip_asn: Optional[str | int], n: int) -> dict:
    """
    This method selects n probes that belong to the same ASN network.

    Args:
        ip_asn (str|int): the ASN network
        n (int): number of probes to select

    Returns:
        dict: the selected probes

    Raises:
        InputError: if the ASN network is None
    """
    if ip_asn is None:
        raise InputError("ip_asn cannot be None")
    probes = {
        "type": "asn",
        "value": ip_asn,
        "requested": n
    }
    return probes


def get_prefix_probes(ip_prefix: Optional[str], n: int) -> dict:
    """
    This method selects n probes that belong to the same ASN network.

    Args:
        ip_prefix (str): the IP prefix family
        n (int): number of probes to select

    Returns:
        dict: the selected probes

    Raises:
        InputError: if the IP prefix is None
    """
    if ip_prefix is None:
        raise InputError("ip_prefix cannot be None")
    probes = {
        "type": "prefix",
        "value": ip_prefix,
        "requested": n
    }
    return probes


def get_country_probes(ip_country_code: Optional[str], n: int) -> dict:
    """
    This method selects n probes that belong to the same country.

    Args:
        ip_country_code (str): the country code
        n (int): number of probes to select

    Returns:
        dict: the selected probes

    Raises:
        InputError: if the country code is None
    """
    if ip_country_code is None:
        raise InputError("ip_country_code cannot be None")
    probes = {
        "type": "country",
        "value": ip_country_code,
        "requested": n
    }
    return probes


def get_area_probes(area: Optional[str], n: int) -> dict:
    """
    This method selects n random probes from all over the world.

    Args:
        area (str): The area of the probes
        n (int): number of probes to select

    Returns:
        dict: the selected probes

    Raises:
        InputError: If area is not valid
    """
    if area is None:
        raise InputError("area cannot be None")
    probes = {
        "type": "area",
        "value": area,
        "requested": n
    }
    return probes


def get_random_probes(n: int) -> dict:
    """
    This method selects n random probes from all over the world.

    Args:
        n (int): number of probes to select

    Returns:
        dict: the selected probes
    """
    return get_area_probes("WW", n)


def get_available_probes_asn_and_prefix(client_ip: str, ip_asn: str, ip_prefix: str, ip_type: str) -> list[int]:
    """
    This method gets the probes available on RIPE Atlas that has the same ASN and prefix as the client IP.
    These probes should also support ipv4 or ipv6, it depends on the type.

    Args:
        client_ip (str): The IP address of the client.
        ip_asn (str): the ASN of the searched network
        ip_prefix(str): the prefix of the respective IP
        ip_type (str): the IP type (ipv4 or ipv6). (not case-sensitive)

    Returns:
        list[int]: A list with the ids of the available probes

    Raises:
        Exception: If the input is invalid
    """
    try:
        ip_asn_number = int(ip_asn.lstrip("AS").lstrip("as"))
    except ValueError as e:
        raise InputError(f"{ip_asn} is not a valid ASN")
    prefix_type: str = "prefix_v4" if ip_type == "ipv4" else "prefix_v6"
    filters = {
        "asn": ip_asn_number,
        prefix_type: ip_prefix,
        "status": 1,  # Connected probes
        "tags": f"system-{ip_type.lower()}-works",
        "is_public": True
    }
    probes = ProbeRequest(
        return_objects=True,
        fields="id",
        page_size=300,
        **filters,
    )
    probe_ids_list: list[int] = []
    for p in probes:
        try:
            probe_ids_list.append(p.id)
        except Exception as e:
            print(f"error (safe): {e}")

    # print(probe_ids_list)
    print(f"asn and prefix list{len(probe_ids_list)}")
    return probe_ids_list


def get_available_probes_asn_and_country(client_ip: str, ip_asn: str, ip_country_code: str, ip_type: str) -> list[int]:
    """
    This method gets the probes available on RIPE Atlas that has the same ASN and prefix as the client IP.
    These probes should also support ipv4 or ipv6, it depends on the type.

    Args:
        client_ip (str): The IP address of the client.
        ip_asn (str): the ASN of the searched network
        ip_country_code(str): the country code of the respective IP
        ip_type (str): the IP type (ipv4 or ipv6). (not case-sensitive)

    Returns:
        list[int]: A list with the ids of the available probes

    Raises:
        Exception: If the input is invalid
    """
    try:
        ip_asn_number = int(ip_asn.lstrip("AS").lstrip("as"))
    except ValueError as e:
        raise InputError(f"{ip_asn} is not a valid ASN")
    filters = {
        "asn": ip_asn_number,
        "country_code": ip_country_code,
        "status": 1,  # Connected probes
        "tags": f"system-{ip_type.lower()}-works",
        "is_public": True
    }
    probes = ProbeRequest(
        return_objects=True,
        fields=["id", "geometry"],
        page_size=300,
        **filters,
    )
    lat_client, lon_client = get_coordinates_for_ip(client_ip)
    probe_ids_dist_list: list[tuple[int, float]] = []
    for p in probes:
        try:
            coordinates = getattr(p, "geometry", {}).get("coordinates")
            if coordinates:
                lon, lat = coordinates
                dist: float = calculate_haversine_distance(lat, lon, lat_client, lon_client)
                probe_ids_dist_list.append((p.id, dist))
            else:
                probe_ids_dist_list.append((p.id, 1000000))  # some large value to put this probe at the end of the list
        except Exception as e:
            print(f"error (safe): {e}")
    probe_ids_dist_list.sort(key=lambda x: x[1])
    probe_ids_list: list[int] = [i for (i, d) in probe_ids_dist_list]

    # print(probe_ids_list)
    print(f"asn and country list {len(probe_ids_list)}")
    return probe_ids_list


def get_available_probes_asn(client_ip: str, ip_asn: str, ip_type: str) -> list[int]:
    """
    This method gets the probes available on RIPE Atlas that has the same ASN as the client IP.
    These probes should also support ipv4 or ipv6, it depends on the type.

    Args:
        client_ip (str): The IP address of the client.
        ip_asn (str): the ASN of the searched network
        ip_type (str): the IP type (ipv4 or ipv6). (not case-sensitive)

    Returns:
        list[int]: A list with the ids of the available probes

    Raises:
        Exception: If the input is invalid
    """
    # in wsl, this command would be for example:
    # ripe-atlas probe-search --prefix NL --status 1 --tag system-ipv4-works
    try:
        ip_asn_number = int(ip_asn.lstrip("AS").lstrip("as"))
    except ValueError as e:
        raise InputError(f"{ip_asn} is not a valid ASN")
    filters = {
        "asn": ip_asn_number,
        "status": 1,  # Connected probes
        "tags": f"system-{ip_type.lower()}-works",
        "is_public": True
    }
    probes = ProbeRequest(
        return_objects=True,
        fields=["id"],
        page_size=250,
        **filters,
    )
    probe_ids_list: list[int] = []
    for p in probes:
        try:
            probe_ids_list.append(p.id)
        except Exception as e:
            print(f"error (safe): {e}")
    print(f"asn list {len(probe_ids_list)}")
    return probe_ids_list


def get_available_probes_prefix(client_ip: str, ip_prefix: str, ip_type: str) -> list[int]:
    """
    This method gets the probes available on RIPE Atlas that has the same prefix as the client IP.
    These probes should also support ipv4 or ipv6, it depends on the type.

    Args:
        client_ip (str): The IP address of the client.
        ip_prefix (str): the ip_prefix of the searched network
        ip_type (str): the IP type (ipv4 or ipv6). It should be lowercase.

    Returns:
        list[int]: A list with the ids of the available probes

    Raises:
        Exception: If the input is invalid
    """
    # in wsl, this command would be for example:
    # ripe-atlas probe-search --prefix NL --status 1 --tag system-ipv4-works
    prefix_type: str = "prefix_v4" if ip_type == "ipv4" else "prefix_v6"
    filters = {
        prefix_type: ip_prefix,
        "status": 1,  # Connected probes
        "tags": f"system-{ip_type.lower()}-works",
        "is_public": True
    }
    probes = ProbeRequest(
        return_objects=True,
        fields=["id"],
        page_size=250,
        **filters,
    )
    probe_ids_list: list[int] = []
    for p in probes:
        try:
            probe_ids_list.append(p.id)
        except Exception as e:
            print(f"error (safe): {e}")
    print(f"prefix list{len(probe_ids_list)}")
    return probe_ids_list


def get_available_probes_country(client_ip: str, country_code: str, ip_type: str) -> list[int]:
    """
    This method gets the probes available on RIPE Atlas that has the same country as the client IP.
    These probes should also support ipv4 or ipv6, it depends on the type.

    Args:
        client_ip (str): The IP address of the client.
        country_code (str): the country code
        ip_type (str): the IP type (ipv4 or ipv6). It should be lowercase.

    Returns:
        list[int]: A list with the ids of the available probes

    Raises:
        Exception: If the input is invalid
    """
    # in wsl, this command would be for example:
    # ripe-atlas probe-search --country NL --status 1 --tag system-ipv4-works
    filters = {
        "country_code": country_code,
        "status": 1,  # Connected probes
        "tags": f"system-{ip_type.lower()}-works",
        "is_public": True
    }
    probes = ProbeRequest(
        return_objects=True,
        fields=["id", "geometry"],
        page_size=600,
        **filters,
    )
    lat_client, lon_client = get_coordinates_for_ip(client_ip)
    probe_ids_dist_list: list[tuple[int, float]] = []
    for p in probes:
        try:
            coordinates = getattr(p, "geometry", {}).get("coordinates")
            if coordinates:
                lon, lat = coordinates
                dist: float = calculate_haversine_distance(lat, lon, lat_client, lon_client)
                probe_ids_dist_list.append((p.id, dist))
            else:
                probe_ids_dist_list.append((p.id, 1000000))  # some large value to put this probe at the end of the list
        except Exception as e:
            print(f"error (safe): {e}")

    probe_ids_dist_list.sort(key=lambda x: x[1])
    probe_ids_list: list[int] = [i for (i, d) in probe_ids_dist_list]

    print(f"country list{len(probe_ids_list)}")
    return probe_ids_list


def consume_probes(probes_requested: int, current_probes_set: set[int], probes_ids: list[int]) -> tuple[int, set[int]]:
    """
    This method takes how many probes we need from probes_ids and put them in current_probes_set. If we found enough probes,
    we ignore the remaining probes.

    Args:
        probes_requested (int): The number of probes that we still need to request before calling this method.
        current_probes_set (set[int]): The set of probes we are currently requesting.
        probes_ids (list[int]): A list with the ids of the probes that we found available, and we want to add them.

    Returns:
        tuple[int, set[int]]: - The remained number of probes still to find.
                              - The updated set of probes that we will use in the measurement.
    """
    if probes_requested < 0:
        raise InputError("Probes_requested cannot be negative")
    # c = 0
    for pb in probes_ids:
        if pb not in current_probes_set:
            current_probes_set.add(pb)
            probes_requested -= 1
            # c += 1
            if probes_requested <= 0:
                # print(c)
                return 0, current_probes_set
    # print(c)
    return probes_requested, current_probes_set

# prefixx = get_prefix_from_ip("89.46.74.148")
# print(prefixx)
# import time
# start = time.time()
# ipp="2a06:93c0::24"#"145.94.210.165"
# print(get_probes("89.46.74.148",6,10))
# end = time.time()
# print(end - start)
