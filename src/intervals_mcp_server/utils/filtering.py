"""
Transformation utilities for cleaning and formatting API responses.
"""


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


def _extract_activity_data(activity: dict) -> dict:
    """
    Extract and format activity data.

    Args:
        activity: Raw activity data from API

    Returns:
        Cleaned and formatted activity data
    """
    activity_data = {
        "id": activity.get("id"),
        "name": activity.get("name"),
        "type": activity.get("type"),
        "description": activity.get("description"),
        "start_date": activity.get("start_date"),
        "start_date_local": activity.get("start_date_local"),
        "distance": activity.get("distance"),
        "moving_time": activity.get("moving_time"),
        "elapsed_time": activity.get("elapsed_time"),
        "coasting_time": activity.get("coasting_time"),
        "average_speed": activity.get("average_speed"),
        "max_speed": activity.get("max_speed"),
        "average_heartrate": activity.get("average_heartrate"),
        "max_heartrate": activity.get("max_heartrate"),
        "average_cadence": activity.get("average_cadence"),
        "avg_lr_balance": activity.get("avg_lr_balance"),
        "average_temp": activity.get("average_temp"),
        "min_temp": activity.get("min_temp"),
        "max_temp": activity.get("max_temp"),
        "total_elevation_gain": activity.get("total_elevation_gain"),
        "total_elevation_loss": activity.get("total_elevation_loss"),
        "calories": activity.get("calories"),
        "commute": activity.get("commute"),
        "race": activity.get("race"),
        "icu_training_load": activity.get("icu_training_load"),
        "icu_atl": activity.get("icu_atl"),
        "icu_ctl": activity.get("icu_ctl"),
        "icu_ftp": activity.get("icu_ftp"),
        "icu_intensity": activity.get("icu_intensity"),
        "icu_recording_time": activity.get("icu_recording_time"),
        "icu_rolling_cp": activity.get("icu_rolling_cp"),
        "icu_rolling_w_prime": activity.get("icu_rolling_w_prime"),
        "icu_rolling_p_max": activity.get("icu_rolling_p_max"),
        "icu_rolling_ftp": activity.get("icu_rolling_ftp"),
        "icu_rolling_ftp_delta": activity.get("icu_rolling_ftp_delta"),
        "icu_joules_above_ftp": activity.get("icu_joules_above_ftp"),
        "icu_max_wbal_depletion": activity.get("icu_max_wbal_depletion"),
        "icu_average_watts": activity.get("icu_average_watts"),
        "icu_weighted_avg_watts": activity.get("icu_weighted_avg_watts"),
        "icu_variability_index": activity.get("icu_variability_index"),
        "icu_efficiency_factor": activity.get("icu_efficiency_factor"),
        "icu_power_hr": activity.get("icu_power_hr"),
        "icu_joules": activity.get("icu_joules"),
        "icu_pm_cp": activity.get("icu_pm_cp"),
        "icu_pm_w_prime": activity.get("icu_pm_w_prime"),
        "icu_pm_p_max": activity.get("icu_pm_p_max"),
        "icu_pm_ftp": activity.get("icu_pm_ftp"),
        "decoupling": activity.get("decoupling"),
        "power_load": activity.get("power_load"),
        "pace_load": activity.get("pace_load"),
        "icu_rpe": activity.get("icu_rpe"),
        "lthr": activity.get("lthr"),
        "hr_load": activity.get("hr_load"),
        "trimp": activity.get("trimp"),
        "strain_score": activity.get("strain_score"),
        "icu_hrr": activity.get("icu_hrr"),
        "average_stride": activity.get("average_stride"),
        "perceived_exertion": activity.get("perceived_exertion"),
        "lengths": activity.get("lengths"),
        "pool_length": activity.get("pool_length"),
        "kg_lifted": activity.get("kg_lifted"),
        "carbs_ingested": activity.get("carbs_ingested"),
        "carbs_used": activity.get("carbs_used"),
        "feel": activity.get("feel"),
        "session_rpe": activity.get("session_rpe"),
        "compliance": activity.get("compliance"),
        "polarization_index": activity.get("polarization_index"),
        "average_altitude": activity.get("average_altitude"),
        "max_altitude": activity.get("max_altitude"),
        "min_altitude": activity.get("min_altitude"),
        "average_weather_temp": activity.get("average_weather_temp"),
        "max_weather_temp": activity.get("max_weather_temp"),
        "min_weather_temp": activity.get("min_weather_temp"),
        "average_feels_like": activity.get("average_feels_like"),
        "max_feels_like": activity.get("max_feels_like"),
        "min_feels_like": activity.get("min_feels_like"),
        "average_wind_speed": activity.get("average_wind_speed"),
        "average_wind_gust": activity.get("average_wind_gust"),
        "prevailing_wind_deg": activity.get("prevailing_wind_deg"),
        "headwind_percent": activity.get("headwind_percent"),
        "tailwind_percent": activity.get("tailwind_percent"),
        "average_clouds": activity.get("average_clouds"),
        "max_rain": activity.get("max_rain"),
        "max_snow": activity.get("max_snow"),
        "icu_zone_times": activity.get("icu_zone_times"),
        "icu_hr_zone_times": activity.get("icu_hr_zone_times"),
        "pace_zone_times": activity.get("pace_zone_times"),
        "interval_summary": activity.get("interval_summary"),
    }
    activity_type = activity.get("type", "")
    if activity_type in ("Run", "VirtualRun", "TrailRun", "Walk"):
        if (pace := activity.get("pace")) is not None:
            activity_data["pace"] = format_pace(pace, "MINS_KM")
        if (gap := activity.get("gap")) is not None:
            activity_data["gap"] = format_pace(gap, "MINS_KM")
        if (avg_speed := activity.get("average_speed")) is not None:
            activity_data["average_speed"] = round(avg_speed * 3.6, 2)
        if (max_speed := activity.get("max_speed")) is not None:
            activity_data["max_speed"] = round(max_speed * 3.6, 2)
    elif activity_type in ("Swim", "OpenWaterSwim"):
        if (pace := activity.get("pace")) is not None:
            activity_data["pace"] = format_pace(pace, "SECS_100M")
    elif activity_type in ("Ride", "VirtualRide", "MountainBikeRide", "GravelRide", "EBikeRide"):
        if (avg_speed := activity.get("average_speed")) is not None:
            activity_data["average_speed"] = round(avg_speed * 3.6, 2)
        if (max_speed := activity.get("max_speed")) is not None:
            activity_data["max_speed"] = round(max_speed * 3.6, 2)
    else:
        activity_data["pace"] = activity.get("pace")
        activity_data["gap"] = activity.get("gap")
    return {k: v for k, v in activity_data.items() if v is not None}


def transform_activities(data: list[dict]) -> list[dict]:
    """
    Transform activities data to clean, formatted response.

    Args:
        data: Raw activities data from API

    Returns:
        List of cleaned and formatted activities
    """
    result = []
    for activity in data:
        if not isinstance(activity, dict):
            continue
        activity_data = _extract_activity_data(activity)
        if activity_data:
            result.append(activity_data)
    return result


def transform_activity_details(data: dict) -> dict:
    """
    Transform activity details data to clean, formatted response.

    Args:
        data: Raw activity details data from API

    Returns:
        Cleaned and formatted activity details
    """
    if not isinstance(data, dict):
        return {}
    return _extract_activity_data(data)
