"""Exact crypto amount math with integers (never floats)."""


def to_units(value: str, decimals: int) -> int:
    value = (value or '0').strip()
    neg = value.startswith('-')
    value = value.lstrip('-')
    i, _, f = value.partition('.')
    units = int(i or '0') * 10**decimals + int((f + '0' * decimals)[:decimals] or '0')
    return -units if neg else units


def format_units(units: int, decimals: int) -> str:
    s = str(units).rjust(decimals + 1, '0')
    int_part, frac = (s[: len(s) - decimals], s[len(s) - decimals:]) if decimals else (s, '')
    frac = frac.rstrip('0')
    return f'{int_part}.{frac}' if frac else int_part


def toman_to_crypto(total_toman: int, rate_toman: int, decimals: int) -> str:
    """Always rounds up so the customer never underpays."""
    scale = 10**decimals
    units = (total_toman * scale + rate_toman - 1) // rate_toman
    return format_units(units, decimals)
