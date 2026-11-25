"""call_weight_ladder.vectors, with a limit and with its overlap check hoisted, lists what the plain enumeration listed."""
import itertools
import random

from decomprepair import call_weight_ladder as ladder


def _reference(found):
    """The enumeration as it was written: every choice, the overlap test inside the depth loop, no limit."""
    seen, out = set(), []
    for count in range(1, ladder.MAX_UNITS + 1):
        for chosen in itertools.combinations(range(len(found)), count):
            for depths in itertools.product(range(1, ladder.MAX_DEPTH + 1), repeat=count):
                total = sum(depths)
                if total > ladder.MAX_WRAPPERS:
                    continue
                spans = [(found[i][0], found[i][1]) for i in chosen]
                if any(s[0] < t[1] and t[0] < s[1] for s, t in itertools.combinations(spans, 2)):
                    continue
                delta = {}
                for i, depth in zip(chosen, depths):
                    for n, c in found[i][3].items():
                        delta[n] = delta.get(n, 0) + c * depth
                key = (tuple(sorted(delta.items())), tuple(sorted({found[i][4] for i in chosen})))
                if key in seen:
                    continue
                seen.add(key)
                out.append((total, dict(zip(chosen, depths)), delta))
    out.sort(key=lambda item: (item[0], len(item[1]), sorted(item[1].items())))
    return out


def _units(rng, n):
    position, found = 0, []
    for _ in range(n):
        length = rng.randint(5, 40)
        names = {rng.choice("abcdefg"): rng.randint(1, 2) for _ in range(rng.randint(1, 3))}
        found.append((position, position + length, "x", names, rng.randint(0, 2)))
        position += length + rng.choice([0, 0, 3]) - rng.choice([0, 0, 0, 4])
    return found


def test_vectors_lists_what_the_plain_enumeration_listed():
    rng = random.Random(2)
    for _ in range(40):
        found = _units(rng, rng.randint(2, 16))
        expected = _reference(found)
        for limit in (None, ladder.LIMIT, 30, 5):
            kept = limit or len(expected)
            assert ladder.vectors(found, limit)[:kept] == expected[:kept]


def test_a_function_with_many_calls_is_not_enumerated_in_full():
    found = [(i * 10, i * 10 + 8, "x", {f"n{i}": 1}, 0) for i in range(120)]  # all distinct: 240 fill early
    assert len(ladder.vectors(found, ladder.LIMIT)) < len(found) ** 2  # the three-call choices were not listed
