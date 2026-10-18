---
name: run-tests
description: How to run tinyutils tests for one module and read failures. Use before and after fixing a bug.
---

# Running tinyutils tests

1. Run the failing module's tests first to see the actual assertion:
   `python3 -m unittest tests.test_<module> -v`
2. Read the assertion message; it shows expected vs actual values.
3. Fix the implementation in `tinyutils/<module>.py`, never the test.
4. Re-run the same command until it passes, then run
   `python3 -m unittest discover -s tests` to check nothing else broke.
