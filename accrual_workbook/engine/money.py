"""Money helpers. All engine amounts are Decimal; rounding is half-up to cents."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0")
CENT = Decimal("0.01")


def D(value) -> Decimal:
    """Parse a value into Decimal. Blank / None -> 0. Accepts '1,234.56' and '(12.00)'."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    text = str(value).strip().replace(",", "").replace("$", "")
    if text == "":
        return ZERO
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        out = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc
    return -out if negative else out


def D_or_none(value) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    return D(value)


def r2(value: Decimal) -> Decimal:
    """Round half-up to 2 decimals."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def dmax(*values: Decimal) -> Decimal:
    return max(values)


def fmt(value: Decimal | None) -> str:
    """$1,234.56 with negatives in parentheses (used in generated sentences)."""
    if value is None:
        return ""
    v = r2(value)
    body = f"${abs(v):,.2f}"
    return f"({body})" if v < 0 else body
