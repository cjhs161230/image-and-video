import json
from pathlib import Path

from image_video.infrastructure.logging import JsonlLogger, redact_sensitive


def test_redact_sensitive_masks_nested_secret_values_and_bearer_tokens() -> None:
    authorization = "Bearer " + "token-value"
    visible_token = "Bearer " + "visible-token-value"
    payload = {
        "api_key": "secret-value",
        "headers": {"Authorization": authorization},
        "nested": [{"app_secret": "application-secret"}],
        "message": f"upstream rejected {visible_token}",
    }

    redacted = redact_sensitive(payload)

    assert redacted["api_key"] == "***"
    assert redacted["headers"]["Authorization"] == "***"
    assert redacted["nested"][0]["app_secret"] == "***"
    assert redacted["message"] == "upstream rejected Bearer ***"


def test_jsonl_logger_writes_redacted_structured_event(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    logger = JsonlLogger(path)

    logger.write(
        level="INFO",
        event="provider_request",
        request_id="req-1",
        data={"api_key": "secret", "frame": 2},
    )

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["level"] == "INFO"
    assert event["event"] == "provider_request"
    assert event["request_id"] == "req-1"
    assert event["data"] == {"api_key": "***", "frame": 2}
    assert event["timestamp"].endswith("Z")
