"""Base62 encoding for short-code generation (standard 0-9A-Za-z alphabet)."""

from __future__ import annotations

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)
_INDEX = {character: index for index, character in enumerate(ALPHABET)}


def encode(number: int) -> str:
    """Encode a non-negative integer as a Base62 string."""
    if number < 0:
        raise ValueError("Base62 encoding requires a non-negative integer")
    if number == 0:
        return ALPHABET[0]

    digits: list[str] = []
    while number:
        number, remainder = divmod(number, BASE)
        digits.append(ALPHABET[remainder])
    return "".join(reversed(digits))


def decode(code: str) -> int:
    """Decode a Base62 string back to its integer."""
    if not code:
        raise ValueError("Cannot decode an empty Base62 string")

    number = 0
    for character in code:
        if character not in _INDEX:
            raise ValueError(f"Invalid Base62 character: {character!r}")
        number = number * BASE + _INDEX[character]
    return number
