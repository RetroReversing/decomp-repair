"""The typed scans (`_scan.pyx`, built by native_build.py) answer exactly what the plain Python ones answer."""
import random

import pytest

from decomprepair import pattern_repairs

scan = pytest.importorskip("decomprepair._scan", reason="the typed scans are not built")


def _outcome(function, *arguments):
    try:
        return function(*arguments)
    except Exception as error:  # the plain scan raises for a start far before the text: so must the typed one
        return type(error)


def test_close_matches_the_plain_scan_on_random_text():
    rng = random.Random(7)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\n", "é", "𝄞", "((", "))"]
    for _ in range(20000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
        start = rng.randint(-3, len(text) + 2)
        for left, right in (("(", ")"), ("{", "}"), ("[", "]"), ("(", "("), ("({", ")}")):
            assert _outcome(scan.close, text, start, left, right) == _outcome(
                pattern_repairs._close, text, start, left, right), (text, start, left, right)


def test_the_library_uses_the_typed_scan_when_it_is_built():
    assert pattern_repairs.close is scan.close


def test_the_c_scan_walkers_match_the_plain_ones_on_random_text():
    from decomprepair import c_scan

    rng = random.Random(8)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\n", ";", "é", "if (a) ", "for (;;) ", "do "]
    for _ in range(20000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
        n = len(text)
        a, b = rng.randint(-3, n + 3), rng.randint(-3, n + 3)
        for left, right in (("{", "}"), ("(", ")"), ("{", "{"), ("{}", "}")):
            assert _outcome(scan.c_close, text, a, left, right) == _outcome(c_scan._close, text, a, left, right), (
                text, a, left, right)
        assert _outcome(scan.c_enclosing_block, text, a, b) == _outcome(c_scan._enclosing_block, text, a, b), (text, a, b)
        assert _outcome(scan.c_header_before, text, a) == _outcome(c_scan._header_before, text, a), (text, a)


def test_the_library_uses_the_typed_c_scan_walkers_when_they_are_built():
    from decomprepair import c_scan

    assert (c_scan.close, c_scan.enclosing_block, c_scan.header_before) == (
        scan.c_close, scan.c_enclosing_block, scan.c_header_before)
