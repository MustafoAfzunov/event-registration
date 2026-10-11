import pytest

from app.errors import DomainError
from app.services.normalize import normalize_email


@pytest.mark.parametrize(
    ("raw", "display", "normalized"),
    [
        ("alice@example.com", "alice@example.com", "alice@example.com"),
        ("  Alice@Example.COM\t", "Alice@Example.COM", "alice@example.com"),
        (
            "first.last+tag@sub.example.org",
            "first.last+tag@sub.example.org",
            "first.last+tag@sub.example.org",
        ),
    ],
)
def test_email_normalized_trim_lower(raw: str, display: str, normalized: str) -> None:
    assert normalize_email(raw) == (display, normalized)


def test_provider_specific_folding_not_applied() -> None:
    # Gmail ignores dots and +tags, other providers don't: we must not merge them (D-014).
    assert normalize_email("a.b+x@gmail.com")[1] != normalize_email("ab@gmail.com")[1]


# Special-use domains (.test, .local) are rejected by email-validator (D-042).
@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        "plain",
        "a@",
        "@b.com",
        "a@b",
        "a b@c.com",
        "ü@example.com",
        "a@site.test",
        "a@host.local",
    ],
)
def test_invalid_email_rejected(raw: str) -> None:
    with pytest.raises(DomainError) as exc:
        normalize_email(raw)
    assert (exc.value.code, exc.value.status) == ("invalid_email", 422)
