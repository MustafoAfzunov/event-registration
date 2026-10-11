from collections import Counter

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from app.services import codes
from tests.helpers import create_event, register, registrations


def test_ticket_code_alphabet_and_length() -> None:
    for _ in range(1000):
        code = codes.new_ticket_code()
        assert len(code) == 8
        assert set(code) <= set(codes.CROCKFORD)
        assert not set(code) & set("ILOU")


def test_ticket_codes_look_random() -> None:
    """Sanity check of the CSPRNG usage: no repeats in 20k codes (expected collisions
    at 40 bits: ~0.0002) and every symbol of the alphabet is used roughly uniformly."""
    sample = [codes.new_ticket_code() for _ in range(20_000)]
    assert len(set(sample)) == len(sample)
    counts = Counter("".join(sample))
    assert set(counts) == set(codes.CROCKFORD)
    expected = 20_000 * 8 / 32
    assert all(0.9 * expected < n < 1.1 * expected for n in counts.values())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ABCD-EFGH", "ABCDEFGH"),
        ("abcd efgh", "ABCDEFGH"),
        (" abcd-efgh ", "ABCDEFGH"),
        ("OOOO-IIII", "00001111"),
        ("llll0000", "11110000"),
        ("ABCDEFG", None),
        ("ABCDEFGHJ", None),
        ("ABCD-EFGU", None),
        ("", None),
    ],
)
def test_code_input_normalization(raw: str, expected: str | None) -> None:
    assert codes.normalize_ticket_input(raw) == expected


def test_manage_token_is_long_and_unique() -> None:
    tokens = {codes.new_manage_token() for _ in range(1000)}
    assert len(tokens) == 1000
    assert all(len(t) >= 43 for t in tokens)


async def test_code_collision_retries(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "first@x.io")
    [existing] = await registrations(engine, event_id)

    # Next generated codes: an existing one (collision!) twice, then a fresh one.
    sequence = iter([existing["ticket_code"], existing["ticket_code"], "ZZZZ9999"])
    monkeypatch.setattr(codes, "new_ticket_code", lambda: next(sequence))

    response = await register(client, event_id, "second@x.io")

    assert response.status_code == 201
    second = [r for r in await registrations(engine, event_id) if r["email"] == "second@x.io"]
    assert second[0]["ticket_code"] == "ZZZZ9999"
