from pydantic import BaseModel, Field


class HazardPayload(BaseModel):
    node_id: str
    timestamp: str = Field(description="ISO-8601 string, display metadata only")
    hazard_type: str
    severity: str = Field(pattern="^(LOW|MEDIUM|HIGH)$")
    coordinates: dict[str, float] = Field(
        description="lat/lng in decimal degrees"
    )

    model_config = {"json_schema_extra": {"examples": [
        {
            "node_id": "node_alpha",
            "timestamp": "2026-07-24T12:34:56Z",
            "hazard_type": "flooding",
            "severity": "HIGH",
            "coordinates": {"lat": 40.7128, "lng": -74.0060}
        }
    ]}}


class EventEnvelope(BaseModel):
    """D5: event wrapper — payload lives inside, identity/order lives here."""
    event_id: str = Field(description="node_id:seq, e.g. 'nodeA:42'")
    node_id: str
    seq: int = Field(ge=1, description="per-node monotonic sequence")
    lamport: int = Field(ge=1, description="Lamport clock for causal ordering")
    payload: HazardPayload
