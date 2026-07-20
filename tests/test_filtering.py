"""
Unit tests for the filtering module in intervals_mcp_server.utils.filtering.

These tests cover all transformation and formatting functions used to clean
and format API responses from Intervals.icu.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

from intervals_mcp_server.utils.filtering import (
    format_pace,
    transform_activities,
    transform_activity_details,
    transform_activity_intervals,
    transform_athlete,
)


class TestFormatPace:
    """Tests for the format_pace function."""

    def test_format_pace_mins_km(self):
        """Test pace formatting for min/km (running)."""
        # 3.17 m/s ≈ 11.4 km/h ≈ 5:15 min/km
        result = format_pace(3.17, "MINS_KM")
        assert result == "5:15"

    def test_format_pace_mins_km_fast(self):
        """Test pace formatting for fast running pace."""
        # 5 m/s = 18 km/h = 3:20 min/km
        result = format_pace(5.0, "MINS_KM")
        assert result == "3:20"

    def test_format_pace_mins_km_slow(self):
        """Test pace formatting for slow running pace."""
        # 2.5 m/s = 9 km/h = 6:40 min/km
        result = format_pace(2.5, "MINS_KM")
        assert result == "6:40"

    def test_format_pace_secs_100m_with_minutes(self):
        """Test pace formatting for swimming (secs/100m) with minutes component."""
        # 1.0 m/s = 100 secs/100m = 1:40
        result = format_pace(1.0, "SECS_100M")
        assert result == "1:40"

    def test_format_pace_secs_100m_under_minute(self):
        """Test pace formatting for fast swimming (under 1 minute per 100m)."""
        # 2.0 m/s = 50 secs/100m
        result = format_pace(2.0, "SECS_100M")
        assert result == "50"

    def test_format_pace_secs_100m_slow(self):
        """Test pace formatting for slow swimming."""
        # 0.8 m/s = 125 secs/100m = 2:05
        result = format_pace(0.8, "SECS_100M")
        assert result == "2:05"

    def test_format_pace_unknown_units(self):
        """Test pace formatting with unknown units returns raw value."""
        result = format_pace(3.5, "UNKNOWN")
        assert result == "3.5"


class TestTransformAthlete:
    """Tests for the transform_athlete function."""

    def test_transform_athlete_basic_fields(self):
        """Test transformation of basic athlete fields."""
        data = {
            "id": "i123",
            "name": "John Doe",
            "firstname": "John",
            "lastname": "Doe",
            "sex": "M",
            "city": "New York",
            "country": "USA",
            "timezone": "America/New_York",
            "icu_weight": 70.5,
        }
        result = transform_athlete(data)
        assert result["id"] == "i123"
        assert result["name"] == "John Doe"
        assert result["firstname"] == "John"
        assert result["lastname"] == "Doe"
        assert result["sex"] == "M"
        assert result["city"] == "New York"
        assert result["country"] == "USA"
        assert result["icu_weight"] == 70.5

    def test_transform_athlete_filters_none_values(self):
        """Test that None values are filtered out."""
        data = {
            "id": "i123",
            "name": None,
            "city": "Boston",
        }
        result = transform_athlete(data)
        assert result["id"] == "i123"
        assert result["city"] == "Boston"
        assert "name" not in result

    def test_transform_athlete_with_sport_settings(self):
        """Test transformation of athlete with sport settings."""
        data = {
            "id": "i123",
            "sportSettings": [
                {
                    "types": ["Run"],
                    "ftp": 250,
                    "lthr": 165,
                    "max_hr": 185,
                    "power_zones": [100, 150, 200, 250, 300],
                }
            ],
        }
        result = transform_athlete(data)
        assert len(result["sportSettings"]) == 1
        assert result["sportSettings"][0]["types"] == ["Run"]
        assert result["sportSettings"][0]["ftp"] == 250
        assert result["sportSettings"][0]["lthr"] == 165

    def test_transform_athlete_with_threshold_pace(self):
        """Test transformation of athlete with threshold pace formatting."""
        data = {
            "id": "i123",
            "sportSettings": [
                {
                    "types": ["Run"],
                    "threshold_pace": 3.17,  # ~5:15 min/km
                    "pace_units": "MINS_KM",
                }
            ],
        }
        result = transform_athlete(data)
        assert result["sportSettings"][0]["threshold_pace"] == "5:15"
        assert result["sportSettings"][0]["threshold_pace_units"] == "MINS_KM"

    def test_transform_athlete_skips_non_dict_sport_settings(self):
        """Test that non-dict items in sportSettings are skipped."""
        data = {
            "id": "i123",
            "sportSettings": [
                {"types": ["Run"], "ftp": 250},
                "invalid",
                None,
                {"types": ["Ride"], "ftp": 280},
            ],
        }
        result = transform_athlete(data)
        assert len(result["sportSettings"]) == 2


class TestTransformActivities:
    """Tests for activity transformation functions."""

    def test_transform_activities_basic(self):
        """Test basic activity list transformation."""
        data = [
            {
                "id": "a1",
                "name": "Morning Run",
                "type": "Run",
                "distance": 10000,
                "moving_time": 3000,
            },
            {
                "id": "a2",
                "name": "Evening Ride",
                "type": "Ride",
                "distance": 50000,
                "moving_time": 7200,
            },
        ]
        result = transform_activities(data)
        assert len(result) == 2
        assert result[0]["id"] == "a1"
        assert result[0]["name"] == "Morning Run"
        assert result[1]["id"] == "a2"

    def test_transform_activities_run_with_pace(self):
        """Test run activity with pace formatting."""
        data = [
            {
                "id": "a1",
                "type": "Run",
                "pace": 3.17,  # ~5:15 min/km
                "gap": 3.0,  # ~5:33 min/km
                "average_speed": 3.17,  # m/s -> 11.41 km/h
                "max_speed": 4.0,  # m/s -> 14.4 km/h
            }
        ]
        result = transform_activities(data)
        assert result[0]["pace"] == "5:15"
        assert result[0]["gap"] == "5:33"
        assert result[0]["average_speed"] == 11.41
        assert result[0]["max_speed"] == 14.4

    def test_transform_activities_swim_with_pace(self):
        """Test swim activity with pace formatting."""
        data = [
            {
                "id": "a1",
                "type": "Swim",
                "pace": 1.0,  # 1:40 per 100m
            }
        ]
        result = transform_activities(data)
        assert result[0]["pace"] == "1:40"

    def test_transform_activities_ride_with_speed(self):
        """Test ride activity with speed conversion."""
        data = [
            {
                "id": "a1",
                "type": "Ride",
                "average_speed": 8.33,  # m/s -> 30 km/h
                "max_speed": 11.11,  # m/s -> 40 km/h
            }
        ]
        result = transform_activities(data)
        assert result[0]["average_speed"] == 29.99
        assert result[0]["max_speed"] == 40.0

    def test_transform_activities_other_type(self):
        """Test other activity type keeps raw values."""
        data = [
            {
                "id": "a1",
                "type": "Workout",
                "pace": 2.5,
                "gap": 2.3,
            }
        ]
        result = transform_activities(data)
        assert result[0]["pace"] == 2.5
        assert result[0]["gap"] == 2.3

    def test_transform_activities_skips_non_dict(self):
        """Test that non-dict items are skipped."""
        data = [
            {"id": "a1", "type": "Run"},
            "invalid",
            None,
            {"id": "a2", "type": "Ride"},
        ]
        result = transform_activities(data)
        assert len(result) == 2

    def test_transform_activities_filters_none_values(self):
        """Test that None values are filtered from activities."""
        data = [
            {
                "id": "a1",
                "name": "Run",
                "type": "Run",
                "description": None,
                "calories": None,
            }
        ]
        result = transform_activities(data)
        assert "description" not in result[0]
        assert "calories" not in result[0]


class TestTransformActivityDetails:
    """Tests for transform_activity_details function."""

    def test_transform_activity_details_basic(self):
        """Test basic activity details transformation."""
        data = {
            "id": "a1",
            "name": "Morning Run",
            "type": "Run",
            "distance": 10000,
        }
        result = transform_activity_details(data)
        assert result["id"] == "a1"
        assert result["name"] == "Morning Run"

    def test_transform_activity_details_non_dict_returns_empty(self):
        """Test that non-dict input returns empty dict."""
        assert transform_activity_details("invalid") == {}
        assert transform_activity_details(None) == {}
        assert transform_activity_details([]) == {}


class TestTransformActivityIntervals:
    """Tests for activity intervals transformation functions."""

    def test_transform_activity_intervals_basic(self):
        """Test basic intervals transformation."""
        data = {
            "id": "a1",
            "analyzed": True,
            "icu_intervals": [
                {
                    "id": 1,
                    "type": "WORK",
                    "distance": 1000,
                    "moving_time": 300,
                    "average_heartrate": 150,
                }
            ],
            "icu_groups": [
                {
                    "id": 100,
                    "type": "WORK",
                    "count": 5,
                }
            ],
        }
        result = transform_activity_intervals(data, "Run")
        assert result["id"] == "a1"
        assert result["analyzed"] is True
        assert len(result["icu_intervals"]) == 1
        assert result["icu_intervals"][0]["id"] == 1
        assert len(result["icu_groups"]) == 1
        assert result["icu_groups"][0]["count"] == 5

    def test_transform_activity_intervals_run_with_pace(self):
        """Test run intervals with pace and speed formatting."""
        data = {
            "id": "a1",
            "icu_intervals": [
                {
                    "id": 1,
                    "gap": 3.17,  # ~5:15 min/km
                    "average_speed": 3.17,  # m/s -> 11.41 km/h
                    "min_speed": 2.5,  # m/s -> 9 km/h
                    "max_speed": 4.0,  # m/s -> 14.4 km/h
                }
            ],
        }
        result = transform_activity_intervals(data, "Run")
        interval = result["icu_intervals"][0]
        assert interval["gap"] == "5:15"
        assert interval["average_speed"] == 11.41
        assert interval["min_speed"] == 9.0
        assert interval["max_speed"] == 14.4

    def test_transform_activity_intervals_swim_with_pace(self):
        """Test swim intervals with pace formatting."""
        data = {
            "id": "a1",
            "icu_intervals": [
                {
                    "id": 1,
                    "average_speed": 1.0,  # 1:40 per 100m
                }
            ],
        }
        result = transform_activity_intervals(data, "Swim")
        assert result["icu_intervals"][0]["pace"] == "1:40"

    def test_transform_activity_intervals_ride_with_speed(self):
        """Test ride intervals with speed conversion."""
        data = {
            "id": "a1",
            "icu_intervals": [
                {
                    "id": 1,
                    "average_speed": 8.33,  # m/s -> ~30 km/h
                    "min_speed": 5.0,  # m/s -> 18 km/h
                    "max_speed": 12.0,  # m/s -> 43.2 km/h
                }
            ],
        }
        result = transform_activity_intervals(data, "Ride")
        interval = result["icu_intervals"][0]
        assert interval["average_speed"] == 29.99
        assert interval["min_speed"] == 18.0
        assert interval["max_speed"] == 43.2

    def test_transform_activity_intervals_other_type(self):
        """Test other activity type keeps raw speed values."""
        data = {
            "id": "a1",
            "icu_intervals": [
                {
                    "id": 1,
                    "average_speed": 5.0,
                    "gap": 3.0,
                }
            ],
        }
        result = transform_activity_intervals(data, "Yoga")
        interval = result["icu_intervals"][0]
        assert interval["average_speed"] == 5.0
        assert interval["gap"] == 3.0

    def test_transform_activity_intervals_non_dict_returns_empty(self):
        """Test that non-dict input returns empty dict."""
        assert transform_activity_intervals("invalid", "Run") == {}
        assert transform_activity_intervals(None, "Run") == {}

    def test_transform_activity_intervals_skips_non_dict_intervals(self):
        """Test that non-dict intervals are skipped."""
        data = {
            "id": "a1",
            "icu_intervals": [
                {"id": 1, "type": "WORK"},
                "invalid",
                None,
                {"id": 2, "type": "REST"},
            ],
            "icu_groups": [
                {"id": 100},
                "invalid",
            ],
        }
        result = transform_activity_intervals(data, "Run")
        assert len(result["icu_intervals"]) == 2
        assert len(result["icu_groups"]) == 1

    def test_transform_activity_intervals_virtual_run(self):
        """Test VirtualRun uses run formatting."""
        data = {
            "id": "a1",
            "icu_intervals": [{"id": 1, "gap": 3.17}],
        }
        result = transform_activity_intervals(data, "VirtualRun")
        assert result["icu_intervals"][0]["gap"] == "5:15"

    def test_transform_activity_intervals_open_water_swim(self):
        """Test OpenWaterSwim uses swim formatting."""
        data = {
            "id": "a1",
            "icu_intervals": [{"id": 1, "average_speed": 1.0}],
        }
        result = transform_activity_intervals(data, "OpenWaterSwim")
        assert result["icu_intervals"][0]["pace"] == "1:40"

    def test_transform_activity_intervals_gravel_ride(self):
        """Test GravelRide uses ride formatting."""
        data = {
            "id": "a1",
            "icu_intervals": [{"id": 1, "average_speed": 8.33}],
        }
        result = transform_activity_intervals(data, "GravelRide")
        assert result["icu_intervals"][0]["average_speed"] == 29.99

    def test_transform_activity_intervals_filters_none_values(self):
        """Test that None values are filtered from intervals."""
        data = {
            "id": "a1",
            "analyzed": None,
            "icu_intervals": [
                {
                    "id": 1,
                    "label": None,
                    "distance": 1000,
                }
            ],
        }
        result = transform_activity_intervals(data, "Run")
        assert "analyzed" not in result
        assert "label" not in result["icu_intervals"][0]
        assert result["icu_intervals"][0]["distance"] == 1000
