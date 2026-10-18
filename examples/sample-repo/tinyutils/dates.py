from datetime import date


def is_leap_year(year: int) -> bool:
    """Gregorian leap year."""
    return year % 4 == 0


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if is_leap_year(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def add_months(d: date, months: int) -> date:
    """Add calendar months, clamping the day to the end of the target month."""
    index = d.month - 1 + months
    year, month = d.year + index // 12, index % 12 + 1
    return date(year, month, min(d.day, days_in_month(year, month)))
