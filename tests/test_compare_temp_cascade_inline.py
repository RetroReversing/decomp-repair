"""m2c's comparison temporaries written back as the chain's own comparisons."""
from decomprepair import compare_temp_cascade_inline as m
from decomprepair.registry import declared

SRC = '''void f(s32 w, s32 h, s32 *out) {
    s32 t1;
    s32 t2;
    t1 = h == 0x40;
    if (t1 && (w == 0x40)) {
        *out = 5;
    } else {
        t2 = w == 0x20;
        if (t2 && (h == 0x80)) {
            *out = 4;
        } else if (t2 & t1) {
            *out = 2;
        } else if (t2 & (h == 0x20)) {
            *out = 1;
        }
    }
}
'''


def kids(source=SRC):
    return [t for fam, t in m.variants(source, 'f') if fam == m.FAMILY]


def test_every_temporary_is_written_into_its_conditions():
    first = kids()[0]
    body = first.split('s32 t2;', 1)[1]
    assert 't1' not in body and 't2' not in body
    assert 'if ((h == 0x40) && (w == 0x40))' in first
    assert 'else if ((w == 0x20) & (h == 0x40))' in first


def test_conditions_are_put_in_the_majority_order():
    both = kids()[1]
    assert 'if ((w == 0x40) && (h == 0x40))' in both
    assert 'if ((w == 0x20) && (h == 0x80))' in both
    assert '(w == 0x20) & (h == 0x40)' in both


def test_an_operand_assigned_in_the_range_blocks_the_inline():
    bad = SRC.replace('*out = 5;', 'h = 2;')
    out = kids(bad)
    assert all('t1 = h' in t or 't1' not in t for t in out)
    assert all('t1 = h == 0x40;' in t for t in out) or out == []


def test_it_declares_itself():
    assert any(r.module == 'compare_temp_cascade_inline' for r in declared())
