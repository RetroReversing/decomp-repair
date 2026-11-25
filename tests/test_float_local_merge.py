"""Two float locals whose lives never overlap, written as one variable."""
from decomprepair import float_local_merge as merge

SOURCE = '''f32 dot(f32 *, f32 *);
f32 f(f32 *p, f32 *q, f32 *r, s32 n) {
    s32 i;
    f32 best;
    f32 d1, d2, e1, e2;

    best = 0.0f;
    for (i = 0; i < n; i++) {
        d1 = dot(p, q);
        d2 = dot(p, r);
        if (d1 >= 0.0f && d2 < 0.0f) {
            e1 = dot(q, r);
            e2 = dot(r, q);
            if (e1 >= 0.0f && e2 >= 0.0f) {
                best = e1 + d1;
            }
        }
    }
    return best;
}
'''


def _children(source=SOURCE):
    return [text for family, text in merge.variants(source, 'f') if family == merge.FAMILY]


def test_a_later_float_local_is_written_as_an_earlier_one_whose_life_ended():
    out = _children()
    # d1 is read after e1 is set, so e1 cannot take d1; d2 is dead by then, so e1 or e2 may take it
    assert any('    f32 d1, d2, e1;' in t and 'd2 = dot(r, q);' in t and 'e2' not in t for t in out)
    assert not any('d1 = dot(q, r);' in t for t in out)


def test_two_merges_at_once_and_the_chain():
    out = _children()
    assert len(out) == len(set(out)) <= merge.LIMIT
    step = next(t for t in out if 'd2 = dot(q, r);' in t and 'e2 = dot(r, q);' in t)
    assert '    f32 d1, d2, e2;' in step


def test_a_value_carried_round_the_loop_or_read_after_it_keeps_its_name():
    carried = SOURCE.replace('        d1 = dot(p, q);\n', '        d1 = d1 + dot(p, q);\n')
    assert not any('d1 = dot(q, r);' in t or 'd1 = dot(r, q);' in t for t in _children(carried))
    after = SOURCE.replace('    return best;', '    return best + e2;')
    assert not any('e2' not in t for t in _children(after))


def test_address_taken_and_logical_and():
    taken = SOURCE.replace('e2 = dot(r, q);', 'e2 = dot(r, &e1);')
    assert not any("e1" not in t.split('{', 1)[1] for t in _children(taken))
    # `x && e1` is not an address
    assert _children()
