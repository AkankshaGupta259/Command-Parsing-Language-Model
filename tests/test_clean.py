"""Unit tests for the teacher-reply cleaning rules (worker/clean.py)."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
import clean  # noqa: E402


def test_valid_record_is_kept():
    bucket, obj = clean.classify(
        "set an alarm for seven am tomorrow",
        '{"intent": "alarm_set", "date": "tomorrow", "time": "seven am", "place": null}',
    )
    assert bucket == "kept"
    assert obj["intent"] == "alarm_set"


def test_invalid_json_is_rejected():
    bucket, _ = clean.classify("anything", "this is not json")
    assert bucket == "invalid_json"


def test_wrong_keys_are_rejected():
    bucket, _ = clean.classify("x", '{"intent": "weather_query", "foo": 1}')
    assert bucket == "bad_keys"


def test_bad_intent_is_rejected():
    bucket, _ = clean.classify(
        "x", '{"intent": "cook_dinner", "date": null, "time": null, "place": null}')
    assert bucket == "bad_intent"


def test_hallucinated_slot_is_rejected():
    # "paris" never appears in the command, so the place slot is a hallucination
    bucket, _ = clean.classify(
        "what is the weather in london",
        '{"intent": "weather_query", "date": null, "time": null, "place": "paris"}',
    )
    assert bucket == "bad_slot"
