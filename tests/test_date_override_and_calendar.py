"""
tests/test_date_override_and_calendar.py

Comprehensive tests for FoM Live Companion date override parsing,
SaveData original vs overridden date preservation, planner bridge execution,
JSON export metadata, and server API settings integration.
"""

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from companion.config import CompanionConfig, load_companion_config, save_companion_config
from companion.json_exporter import plan_to_json
from companion.planner_bridge import execute_plan, parse_date_override
from companion.server import app, state
from fom_planner.constants import SATURDAY_MARKET_VENDORS
from fom_planner.models import InGameDate, SaveData


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parent.parent


def test_parse_date_override_empty_and_null():
    """Verify empty/falsy/null override strings return None."""
    assert parse_date_override(None) is None
    assert parse_date_override("") is None
    assert parse_date_override("   ") is None
    assert parse_date_override("auto") is None
    assert parse_date_override("save") is None
    assert parse_date_override("default") is None
    assert parse_date_override("none") is None
    assert parse_date_override("0") is None


def test_parse_date_override_saturday():
    """Verify Saturday keyword jumps to upcoming Saturday."""
    ref_date = InGameDate(year=1, season="spring", day=2)
    parsed = parse_date_override("saturday", ref_date)
    assert parsed is not None
    assert parsed.season == "spring"
    assert parsed.day == 6
    assert parsed.is_saturday is True

    # Rollover when day is 28
    ref_end = InGameDate(year=1, season="spring", day=28)
    parsed_rollover = parse_date_override("sat", ref_end)
    assert parsed_rollover is not None
    assert parsed_rollover.season == "summer"
    assert parsed_rollover.day == 6
    assert parsed_rollover.is_saturday is True

    # Without reference date
    parsed_no_ref = parse_date_override("saturday", None)
    assert parsed_no_ref is not None
    assert parsed_no_ref.season == "spring"
    assert parsed_no_ref.day == 6


def test_parse_date_override_explicit_dates():
    """Verify parsing of full date strings across seasons and years."""
    p1 = parse_date_override("Spring 14")
    assert p1 is not None
    assert p1.season == "spring"
    assert p1.day == 14
    assert p1.year == 1

    p2 = parse_date_override("Year 2, Summer 6")
    assert p2 is not None
    assert p2.season == "summer"
    assert p2.day == 6
    assert p2.year == 2
    assert p2.is_saturday is True

    p3 = parse_date_override("Fall 10, Year 3")
    assert p3 is not None
    assert p3.season == "fall"
    assert p3.day == 10
    assert p3.year == 3

    p4 = parse_date_override("autumn 20")
    assert p4 is not None
    assert p4.season == "fall"
    assert p4.day == 20

    p5 = parse_date_override("Winter 28")
    assert p5 is not None
    assert p5.season == "winter"
    assert p5.day == 28


def test_parse_date_override_festivals():
    """Verify festival names resolve to their respective FoM calendar dates."""
    p_animal = parse_date_override("Animal Festival")
    assert p_animal is not None
    assert p_animal.season == "winter"
    assert p_animal.day == 10
    assert p_animal.is_animal_festival is True

    p_spring = parse_date_override("Spring Festival")
    assert p_spring is not None
    assert p_spring.season == "spring"
    assert p_spring.day == 17

    p_star = parse_date_override("Shooting Star Festival")
    assert p_star is not None
    assert p_star.season == "summer"
    assert p_star.day == 28

    p_harvest = parse_date_override("Harvest Festival")
    assert p_harvest is not None
    assert p_harvest.season == "fall"
    assert p_harvest.day == 10


def test_parse_date_override_json_and_numbers():
    """Verify JSON structures and raw numbers are parsed."""
    p_json = parse_date_override('{"season": "summer", "day": 13, "year": 2}')
    assert p_json is not None
    assert p_json.season == "summer"
    assert p_json.day == 13
    assert p_json.year == 2
    assert p_json.is_saturday is True

    ref_date = InGameDate(year=2, season="winter", day=5)
    p_num = parse_date_override("20", ref_date)
    assert p_num is not None
    assert p_num.season == "winter"
    assert p_num.day == 20
    assert p_num.year == 2


def test_save_data_original_in_game_date(repo_root):
    """Verify SaveData retains original_in_game_date when overridden."""
    config = CompanionConfig(strategy="journal", mode="auto", slots=20)
    save, _, _, _ = execute_plan(config, repo_root)
    if save is not None:
        orig = save.original_in_game_date
        assert orig is not None
        assert 1 <= orig.day <= 28

        # Apply override
        override_target = InGameDate(year=5, season="winter", day=10)
        save.in_game_date = override_target

        assert save.in_game_date.year == 5
        assert save.in_game_date.season == "winter"
        assert save.in_game_date.day == 10
        # original date must remain intact
        assert save.original_in_game_date.year == orig.year
        assert save.original_in_game_date.season == orig.season
        assert save.original_in_game_date.day == orig.day


def test_execute_plan_saturday_override(repo_root):
    """Verify setting date_override to a Saturday activates Saturday Market mode."""
    config = CompanionConfig(
        strategy="journal",
        mode="auto",
        date_override="saturday",
        slots=20,
    )
    save, plan_res, meta, save_path = execute_plan(config, repo_root)
    assert save is not None
    assert save.in_game_date.is_saturday is True

    # Check exported JSON
    exported = plan_to_json(save, plan_res, meta, save_path, config)
    date_info = exported["in_game_date"]
    assert date_info["is_saturday"] is True
    assert date_info["is_overridden"] is True
    assert date_info["date_override"] == "saturday"
    assert date_info["save_date"] is not None


def test_execute_plan_non_saturday_override(repo_root):
    """Verify setting date_override to a weekday does not flag Saturday Market."""
    config = CompanionConfig(
        strategy="journal",
        mode="auto",
        date_override="Spring 2, Year 1",
        slots=20,
    )
    save, plan_res, meta, save_path = execute_plan(config, repo_root)
    assert save is not None
    assert save.in_game_date.is_saturday is False
    assert save.in_game_date.day == 2
    assert save.in_game_date.season.lower() == "spring"

    exported = plan_to_json(save, plan_res, meta, save_path, config)
    date_info = exported["in_game_date"]
    assert date_info["is_saturday"] is False
    assert date_info["is_overridden"] is True
    assert date_info["day"] == 2
    assert date_info["season"] == "Spring"


def test_execute_plan_animal_festival_override(repo_root):
    """Verify Winter 10 Animal Festival override captures festival."""
    config = CompanionConfig(
        strategy="journal",
        mode="auto",
        date_override="Winter 10, Year 1",
        slots=20,
    )
    save, plan_res, meta, save_path = execute_plan(config, repo_root)
    assert save is not None
    assert save.in_game_date.is_animal_festival is True
    assert save.in_game_date.festival_name == "Animal Festival"


def test_api_date_override_integration():
    """Verify /api/settings and /api/plan seamlessly accept and reflect date override."""
    client = TestClient(app)

    # 1. Update date override to a Saturday
    res_post = client.post("/api/settings", json={"date_override": "Summer 6, Year 2"})
    assert res_post.status_code == 200
    data_post = res_post.json()
    assert data_post["config"]["date_override"] == "Summer 6, Year 2"

    plan = data_post["plan"]
    assert plan["in_game_date"]["is_overridden"] is True
    assert plan["in_game_date"]["is_saturday"] is True
    assert plan["in_game_date"]["season"] == "Summer"
    assert plan["in_game_date"]["day"] == 6
    assert plan["in_game_date"]["year"] == 2

    # 2. Query /api/plan directly
    res_plan = client.get("/api/plan")
    assert res_plan.status_code == 200
    plan_get = res_plan.json()
    assert plan_get["in_game_date"]["is_overridden"] is True
    assert plan_get["in_game_date"]["is_saturday"] is True

    # 3. Clear date override
    res_clear = client.post("/api/settings", json={"date_override": ""})
    assert res_clear.status_code == 200
    plan_cleared = res_clear.json()["plan"]
    assert plan_cleared["in_game_date"]["is_overridden"] is False
    assert plan_cleared["in_game_date"]["date_override"] == ""


def test_calendar_ui_saturday_button_removed_and_done_applied(repo_root):
    """Verify that Saturday quick buttons are removed from UI and selecting a day only commits on Done."""
    app_js_path = repo_root / "companion" / "static" / "app.js"
    index_html_path = repo_root / "companion" / "static" / "index.html"

    assert app_js_path.exists()
    assert index_html_path.exists()

    app_js = app_js_path.read_text(encoding="utf-8")
    index_html = index_html_path.read_text(encoding="utf-8")

    # 1. Saturday buttons must NOT exist in the DOM or listeners
    assert "sidebarNextSatBtn" not in app_js
    assert "calJumpSaturdayBtn" not in app_js
    assert "calJumpSaturdayBtn" not in index_html
    assert "★ Saturday" not in app_js

    # 2. Calendar button still exists in sidebar
    assert "sidebarOpenCalBtn" in app_js
    assert "📅 Open Calendar" in app_js

    # 3. Calendar Done button applies the staged date override
    assert "applyCalendarModalDone" in app_js
    assert "calCloseBtn.addEventListener" in app_js
    assert "applyCalendarModalDone()" in app_js

    # 4. Selecting a day updates modal state and visual grid without calling submitSettingUpdate
    assert "function selectCalendarDay(day)" in app_js
    # Ensure selectCalendarDay does not directly submit
    select_day_fn_body = app_js.split("function selectCalendarDay(day) {")[1].split("async function applyCalendarModalDone")[0]
    assert "submitSettingUpdate" not in select_day_fn_body
    assert "calModalState.isDirty = true" in select_day_fn_body

