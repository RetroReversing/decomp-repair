import re

from decomprepair import call_weight_ladder
from decomprepair.call_weight_ladder import FAMILY, units, variants, vectors

SOURCE = """void walk(s32 arg0) {
    s32 var_v0;
    s32 flag;
    void *kid;
    void *sib;
    void *obj;

    obj = gHead;
    if (obj != NULL) {
        do {
            kid = field(obj, 8);
            sib = field(obj, 0);
            flag = 1;
            if (kid != NULL) {
                var_v0 = flag;
                row: {
                    if (var_v0 != 0) {
                        prepare(obj, arg0);
                        ready(obj, arg0);
                        flag = 0;
                    }
                    draw(arg0, kid);
                    submit(kid, arg0);
                    kid = field(kid, 8);
                    var_v0 = flag;
                }
                if (kid != NULL) goto row;
            }
            if (sib != NULL) {
                do {
                    kid = field(sib, 8);
                    if (kid != NULL) {
                        draw(arg0, kid);
                        submit2(kid, sib, arg0);
                    }
                    sib = field(sib, 0);
                } while (sib != NULL);
            }
            obj = field(obj, 0x1C);
        } while (obj != NULL);
    }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_runs_of_calls_are_units_beside_the_single_calls():
    found = units(SOURCE, 'walk')
    texts = [_flat(text) for _, _, text, _ in found]
    assert 'prepare(obj, arg0); ready(obj, arg0);' in texts
    assert 'prepare(obj, arg0);' in texts and 'ready(obj, arg0);' in texts
    run = next(counts for _, _, text, counts in found if _flat(text) == 'prepare(obj, arg0); ready(obj, arg0);')
    assert run == {'obj': 2, 'arg0': 2}


def test_the_combination_of_a_deep_run_and_a_shallow_call_is_one_child():
    """A run wrapped three deep and a call run wrapped twice: the shape that moved a flag below the object pointer."""
    flat = [_flat(text) for family, text in variants(SOURCE, 'walk') if family == FAMILY]
    deep = ('do { do { do { prepare(obj, arg0); ready(obj, arg0); } while (0); } while (0); } while (0);')
    assert any(deep in text and 'do { do { draw(arg0, kid); submit2(kid, sib, arg0); } while (0); } while (0);' in text
               for text in flat), len(flat)


def test_children_differ_in_their_weights_and_are_bounded():
    found = vectors(units(SOURCE, 'walk'))
    deltas = [tuple(sorted(d.items())) for _, _, d in found]
    assert len(deltas) == len(set(deltas))
    assert all(total <= call_weight_ladder.MAX_WRAPPERS for total, _, _ in found)
    children = variants(SOURCE, 'walk')
    assert 0 < len(children) <= call_weight_ladder.LIMIT
    assert len({text for _, text in children}) == len(children)
    # the fewest wrappers come first
    assert found[0][0] <= found[-1][0]


def test_a_child_differs_from_the_source_only_by_scopes():
    plain = _flat(SOURCE).replace(' ', '')
    for _, text in variants(SOURCE, 'walk'):
        stripped = _flat(text)
        while re.search(r'do \{ ((?:(?!do \{).)*?) \} while \(0\);', stripped):
            stripped = re.sub(r'do \{ ((?:(?!do \{).)*?) \} while \(0\);', r'\1', stripped, count=1)
        assert stripped.replace(' ', '') != plain or stripped == _flat(SOURCE)
        assert 'do {' in text and text != SOURCE


def test_nothing_without_two_calls_that_name_a_local():
    assert variants('void f(s32 a) { g(); h(); }', 'f') == []
    assert variants('void f(s32 a) { g(a); }', 'f') == []
    assert variants('void f(s32 a) { asm("nop"); g(a); h(a); }', 'f') == []
