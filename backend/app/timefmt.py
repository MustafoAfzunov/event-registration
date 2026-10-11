from datetime import UTC, datetime


def iso_utc(value: datetime) -> str:
    """The one wire format for timestamps (docs/API.md): ISO-8601 in UTC with 'Z'."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
