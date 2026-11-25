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
