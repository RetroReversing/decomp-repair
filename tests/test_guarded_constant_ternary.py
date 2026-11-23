"""A constant local overwritten under a test, as the `?:` it came from (a 1300-instruction routine, 1245 -> 610)."""
from decomprepair.guarded_constant_ternary import FAMILY, REPAIR, variants

SOURCE = """void steer(Obj *o, f32 x)
{
    f32 t;
    s32 n;
    t = 0.4f;
    if (!(x <= 0.0002f) | !(x >= (-0.0002f)))
    {
        t = 0.1f;
    }
    o->t = (x - o->t) * t;
    n = 3;
    if (o->mode == 2) n = 0x10;
    o->n = n;
}
"""


def children(source):
    return [text for family, text in variants(source, 'steer') if family == FAMILY]


def test_both_sites_together_first_then_each():
    found = children(SOURCE)
    assert len(found) == 3
    assert 't = (!(x <= 0.0002f) | !(x >= (-0.0002f))) ? 0.1f : 0.4f;\n    o->t = (x - o->t) * t;' in found[0]
    assert 'n = (o->mode == 2) ? 0x10 : 3;\n    o->n = n;' in found[0]
    assert 'if' not in found[0].split('{', 1)[1]
    assert found[1].count('if (') == 1 and found[2].count('if (') == 1


def test_an_else_or_a_computed_value_is_left_alone():
    assert children(SOURCE.replace('    o->n = n;\n', '    else n = 1;\n    o->n = n;\n')
                    .replace('    t = 0.4f;\n', '    t = x;\n')) == []


def test_a_condition_that_reads_the_local_is_left_alone():
    source = SOURCE.replace('if (o->mode == 2) n = 0x10;', 'if (n == 2) n = 0x10;')
    assert len(children(source)) == 1


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and REPAIR['families'] == (FAMILY,)
