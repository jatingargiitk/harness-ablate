def split_amount(total_cents: int, parts: int) -> list[int]:
    """Split an amount into near-equal integer parts that add up to the total."""
    if parts <= 0:
        raise ValueError("parts must be positive")
    share = total_cents // parts
    return [share] * parts


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"
