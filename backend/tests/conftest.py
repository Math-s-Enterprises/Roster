"""Fixtures shared across the test suite.

`client` — the app wired to an in-memory database — was defined in
`test_api.py`, so every other file that wanted it had to import it by name.
That works, but pytest then sees the import shadowed by each test's own
`client` parameter, and the real cost is that a new API test file fails at
collection with "fixture 'client' not found" until somebody remembers the
trick.

Re-exported here instead. A module-local fixture still wins, so `test_api`
is unaffected.
"""
from tests.test_api import client  # noqa: F401
