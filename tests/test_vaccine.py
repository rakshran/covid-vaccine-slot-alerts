"""Unit tests for the vaccine slot alert Lambda."""

import re

import vaccine

# A representative slice of a Co-WIN calendarByDistrict response.
SAMPLE_PAYLOAD = {
    "centers": [
        {
            "name": "City Hospital",
            "address": "12 Main Road",
            "pincode": 560001,
            "sessions": [
                # Matches: 18+ with capacity.
                {"date": "17-06-2026", "min_age_limit": 18, "available_capacity": 25},
                # Excluded: no capacity.
                {"date": "18-06-2026", "min_age_limit": 18, "available_capacity": 0},
                # Excluded: wrong age group.
                {"date": "18-06-2026", "min_age_limit": 45, "available_capacity": 10},
            ],
        },
        {
            "name": "Community Clinic",
            "address": "9 Park Street",
            "pincode": 560002,
            "sessions": [
                # Matches: 18+ with capacity.
                {"date": "17-06-2026", "min_age_limit": 18, "available_capacity": 3},
            ],
        },
    ]
}


def test_filter_available_slots_matches_age_and_capacity():
    slots = vaccine.filter_available_slots(SAMPLE_PAYLOAD, min_age=18)
    assert len(slots) == 2
    names = {slot["name"] for slot in slots}
    assert names == {"City Hospital", "Community Clinic"}
    assert all(slot["available_capacity"] > 0 for slot in slots)


def test_filter_available_slots_respects_min_age():
    # The only 45+ session has capacity 10, so it is the single match for 45.
    slots = vaccine.filter_available_slots(SAMPLE_PAYLOAD, min_age=45)
    assert len(slots) == 1
    assert slots[0]["available_capacity"] == 10


def test_filter_available_slots_empty_centers():
    assert vaccine.filter_available_slots({"centers": []}, min_age=18) == []
    assert vaccine.filter_available_slots({}, min_age=18) == []


def test_format_message_contains_slot_details():
    slots = vaccine.filter_available_slots(SAMPLE_PAYLOAD, min_age=18)
    message = vaccine.format_message(slots)
    lines = message.split("\n")
    assert len(lines) == 2
    assert "City Hospital" in message
    assert "560001" in message
    assert "25 slots" in message


def test_format_message_empty():
    assert vaccine.format_message([]) == ""


def test_get_today_format():
    today = vaccine.get_today()
    assert re.fullmatch(r"\d{2}-\d{2}-\d{4}", today)
