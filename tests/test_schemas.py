import pytest
from src.ai_engine.schemas import HazardPayload, EventEnvelope


def test_hazard_payload_valid():
    """Test valid hazard payload."""
    hazard = HazardPayload(
        node_id="node_alpha",
        timestamp="2026-07-24T12:34:56Z",
        hazard_type="flooding",
        severity="HIGH",
        coordinates={"lat": 40.7128, "lng": -74.0060}
    )
    assert hazard.node_id == "node_alpha"
    assert hazard.severity == "HIGH"


def test_hazard_payload_invalid_severity():
    """Test invalid severity level."""
    with pytest.raises(ValueError):
        HazardPayload(
            node_id="node_alpha",
            timestamp="2026-07-24T12:34:56Z",
            hazard_type="flooding",
            severity="CRITICAL",  # Invalid
            coordinates={"lat": 0, "lng": 0}
        )


def test_event_envelope():
    """Test event envelope wraps payload."""
    payload = HazardPayload(
        node_id="node_alpha",
        timestamp="2026-07-24T12:34:56Z",
        hazard_type="flooding",
        severity="MEDIUM",
        coordinates={"lat": 0, "lng": 0}
    )
    envelope = EventEnvelope(
        event_id="node_alpha:1",
        node_id="node_alpha",
        seq=1,
        lamport=1,
        payload=payload
    )
    assert envelope.event_id == "node_alpha:1"
    assert envelope.payload.hazard_type == "flooding"
