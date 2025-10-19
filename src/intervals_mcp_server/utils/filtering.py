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


def filter_response_data(data: Any, blacklist: set[str] | None = None, keep_scalars_only: bool = True) -> Any:
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
        return [filter_response_data(item, blacklist, keep_scalars_only) for item in data]
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
