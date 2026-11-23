"""compose: children of one source merged when their edits are independent, ranked by the rows they leave."""
from decomprepair import compose

BASE = 'int f(int a) {\n    int x = a + 1;\n    int y = a * 2;\n    return x - y;\n}\n'
ONE = BASE.replace('a + 1', '1 + a')
TWO = BASE.replace('a * 2', 'a << 1')
CLASH = BASE.replace('a + 1', 'a + 2')


def test_independent_edits_merge_and_overlapping_ones_do_not():
    merged = compose.merge(BASE, [ONE, TWO])
    assert '1 + a' in merged and 'a << 1' in merged
    assert compose.merge(BASE, [ONE, CLASH]) is None
    assert compose.merge(BASE, [ONE, BASE]) is None  # a child that changes nothing is not an edit


def test_rank_puts_fewest_rows_first_and_caps_each_family():
    items = [(9, 10, 'a', 'a1'), (2, 90, 'b', 'b1'), (2, 50, 'c', 'c1'), (None, 1, 'd', 'd1'), (3, None, 'e', 'e1'),
             (1, 99, 'a', 'a2'), (4, 5, 'a', 'a3')]
    ranked = compose.rank(items, top=10, per_family=2)
    assert [item[3] for item in ranked] == ['a2', 'c1', 'b1', 'a3', 'd1']


def test_compositions_pair_different_families_then_triples():
    three = BASE.replace('x - y', 'y - x')
    ranked = [(1, 5, 'p', ONE), (1, 6, 'q', TWO), (2, 7, 'r', three), (2, 8, 'p', CLASH)]
    out = compose.compositions(BASE, ranked)
    names = [name for name, _ in out]
    assert names[:3] == ['p+q', 'p+r', 'q+r'] and 'p+p' not in names
    assert 'p+q+r' in names
    (triple,) = [text for name, text in out if name == 'p+q+r']
    assert '1 + a' in triple and 'a << 1' in triple and 'y - x' in triple
    assert 'q+p' in names  # CLASH (family p) with TWO: independent edits, different families
    assert all(text != BASE for _, text in out)
    assert compose.compositions(BASE, ranked, triples=False, limit=2) == out[:2]
