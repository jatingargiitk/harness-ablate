def to_csv(rows: list[dict], columns: list[str]) -> str:
    """Render rows as CSV text with a header line."""
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(str(row.get(c, "")) for c in columns))
    return "\n".join(lines) + "\n"
