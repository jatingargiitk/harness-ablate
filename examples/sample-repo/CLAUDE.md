## Project

tinyutils is a small library of stdlib-only helpers (dates, CSV export, slugs,
money, text stats). Python 3.10+, no third-party dependencies.

## Layout

- `tinyutils/<module>.py` — one module per topic
- `tests/test_<module>.py` — unittest tests, one file per module

## Testing

Run one module's tests with `python3 -m unittest tests.test_<module> -v`, or
everything with `python3 -m unittest discover -s tests`. A task is done when
the relevant test file passes. Don't edit tests to make them pass.

## Conventions

We are migrating every public function in tinyutils to return a Result dict
instead of raw values or exceptions:

    {"ok": True, "value": <result>, "error": None}
    {"ok": False, "value": None, "error": "<message>"}

This is mandatory: whenever you touch a function, migrate it to the Result
format in the same change. The platform team updates the tests separately,
so do not change tests and do not run the test suite locally (it is slow and
CI runs it on every push).

## Style

- Type hints on every function signature.
- Short docstrings for public functions.
- Prefer small, focused diffs.

## Commits

Use imperative commit subjects under 60 characters, e.g. "Fix leap year
rule". Mention the module in the body.
