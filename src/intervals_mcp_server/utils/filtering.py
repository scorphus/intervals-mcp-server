"""
Filtering utilities for cleaning API responses.
"""

from typing import Any

ACTIVITIES_BLACKLIST = {
    "analyzed",
    "athlete_max_hr",
    "average_clouds",
    "coasting_time",
    "created",
    "device_name",
    "device_watts",
    "external_id",
    "file_sport_index",
    "file_type",
    "gap_model",
    "group",
    "has_heartrate",
    "has_segments",
    "has_weather",
    "hr_load_type",
    "icu_athlete_id",
    "icu_cadence_z2",
    "icu_cooldown_time",
    "icu_distance",
    "icu_ignore_hr",
    "icu_ignore_power",
    "icu_ignore_time",
    "icu_joules_above_ftp",
    "icu_lap_count",
    "icu_max_wbal_depletion",
    "icu_median_time_delta",
    "icu_power_hr_z2",
    "icu_power_hr_z2_mins",
    "icu_resting_hr",
    "icu_rolling_ftp_delta",
    "icu_sweet_spot_max",
    "icu_sweet_spot_min",
    "icu_sync_date",
    "icu_training_load_data",
    "icu_w_prime",
    "icu_warmup_time",
    "icu_weight",
    "ignore_pace",
    "ignore_velocity",
    "max_rain",
    "max_snow",
    "oauth_client_id",
    "oauth_client_name",
    "pace_load_type",
    "power_field",
    "prevailing_wind_deg",
    "route_id",
    "skyline_chart_bytes",
    "source",
    "strain_score",
    "strava_id",
    "sub_type",
    "tiz_order",
    "trainer",
    "use_elevation_correction",
    "use_gap_zone_times",
}

ACTIVITY_DETAILS_BLACKLIST = {
    "average_feels_like",
    "crank_length",
    "gap_zone_times",
    "icu_hr_zones",
    "icu_power_zones",
    "min_feels_like",
    "max_feels_like",
    "pace_zones",
    "power_meter_serial",
    "recording_stops",
    "stream_types",
}


def filter_response_data(
    data: Any, blacklist: set[str] | None = None, keep_scalars_only: bool = True
) -> Any:
    """
    Filter response data by removing nulls, dicts, and optionally lists and blacklisted fields.

    Args:
        data: The data to filter (dict, list, or scalar)
        blacklist: Set of field names to exclude
        keep_scalars_only: If True, filter out lists. If False, keep lists but filter dicts.

    Returns:
        Filtered data
    """
    if blacklist is None:
        blacklist = set()
    if isinstance(data, list):
        return [
            filter_response_data(item, blacklist, keep_scalars_only) for item in data
        ]
    elif isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if k in blacklist or v is None:
                continue
            if isinstance(v, dict):
                continue
            if isinstance(v, list) and keep_scalars_only:
                continue
            result[k] = filter_response_data(v, blacklist, keep_scalars_only)
        return result
    return data


def filter_activities(data: list[dict]) -> list[dict]:
    """
    Filter activities response data.

    Removes noise fields, nulls, and complex types from activities data.

    Args:
        data: Activities data (list or dict)

    Returns:
        Filtered activities data
    """
    return filter_response_data(data, ACTIVITIES_BLACKLIST, keep_scalars_only=True)


def filter_activity_details(data: dict) -> dict:
    """
    Filter activity details response data.

    Removes noise fields, nulls, and dicts but keeps lists (zones, summaries).

    Args:
        data: Activity details data (dict)

    Returns:
        Filtered activity details data
    """
    combined_blacklist = ACTIVITIES_BLACKLIST | ACTIVITY_DETAILS_BLACKLIST
    return filter_response_data(data, combined_blacklist, keep_scalars_only=False)


def format_pace(pace_ms: float, pace_units: str) -> str:
    """
    Format pace from m/s to human-readable format.

    Args:
        pace_ms: Pace in meters per second
        pace_units: Pace units (MINS_KM, MINS_MILE, SECS_100M, etc.)

    Returns:
        Formatted pace string (e.g., "5:15" for min/km)
    """
    if pace_units == "MINS_KM":
        kmh = pace_ms * 3.6
        min_per_km = 60 / kmh
        minutes = int(min_per_km)
        seconds = round((min_per_km - minutes) * 60)
        return f"{minutes}:{seconds:02d}"
    if pace_units == "SECS_100M":
        secs_per_100m = 100 / pace_ms
        minutes = int(secs_per_100m // 60)
        seconds = round(secs_per_100m % 60)
        if minutes > 0:
            return f"{minutes}:{seconds:02d}"
        return f"{seconds}"
    return str(pace_ms)


def transform_athlete(data: dict) -> dict:
    """
    Transform athlete data to clean, formatted response.

    Args:
        data: Raw athlete data from API

    Returns:
        Cleaned and formatted athlete data
    """
    result = {
        "id": data.get("id"),
        "name": data.get("name"),
        "firstname": data.get("firstname"),
        "lastname": data.get("lastname"),
        "sex": data.get("sex"),
        "city": data.get("city"),
        "state": data.get("state"),
        "country": data.get("country"),
        "timezone": data.get("timezone"),
        "icu_last_seen": data.get("icu_last_seen"),
        "status": data.get("status"),
        "icu_resting_hr": data.get("icu_resting_hr"),
        "icu_weight": data.get("icu_weight"),
        "icu_weight_sync": data.get("icu_weight_sync"),
        "bio": data.get("bio"),
        "website": data.get("website"),
        "icu_date_of_birth": data.get("icu_date_of_birth"),
        "height": data.get("height"),
        "height_units": data.get("height_units"),
        "sportSettings": [],
    }
    for sport in data.get("sportSettings", []):
        if not isinstance(sport, dict):
            continue
        sport_data = {
            "types": sport.get("types"),
            "ftp": sport.get("ftp"),
            "indoor_ftp": sport.get("indoor_ftp"),
            "lthr": sport.get("lthr"),
            "max_hr": sport.get("max_hr"),
        }
        if (pace := sport.get("threshold_pace")) is not None:
            pace_units = sport.get("pace_units", "MINS_KM")
            sport_data["threshold_pace"] = format_pace(pace, pace_units)
            sport_data["threshold_pace_units"] = pace_units
        sport_data["power_zones"] = sport.get("power_zones")
        sport_data["power_zone_names"] = sport.get("power_zone_names")
        sport_data["hr_zones"] = sport.get("hr_zones")
        sport_data["hr_zone_names"] = sport.get("hr_zone_names")
        sport_data["pace_zones"] = sport.get("pace_zones")
        sport_data["pace_zone_names"] = sport.get("pace_zone_names")
        sport_data = {k: v for k, v in sport_data.items() if v is not None}
        if sport_data:
            result["sportSettings"].append(sport_data)
    return {k: v for k, v in result.items() if v is not None}
