"""Importing the library gives the regex cache room for the families' patterns (and never takes any away)."""
import re

import decomprepair  # noqa: F401


def test_the_regex_cache_has_room_for_the_families_patterns():
    for limit in ("_MAXCACHE", "_MAXCACHE2"):
        if hasattr(re, limit):
            assert getattr(re, limit) >= 4096
