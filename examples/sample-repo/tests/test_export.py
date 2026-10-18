import csv
import io
import unittest

from tinyutils.export import to_csv


class TestExport(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(to_csv([{"a": 1, "b": 2}], ["a", "b"]), "a,b\n1,2\n")

    def test_round_trips_commas_quotes_and_newlines(self):
        rows = [{"name": "Smith, Jane", "note": 'said "hi"'}, {"name": "Bob", "note": "line1\nline2"}]
        text = to_csv(rows, ["name", "note"])
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(parsed, [{k: str(v) for k, v in r.items()} for r in rows])

    def test_missing_values_are_empty(self):
        self.assertEqual(to_csv([{"a": 1}], ["a", "b"]), "a,b\n1,\n")


if __name__ == "__main__":
    unittest.main()
