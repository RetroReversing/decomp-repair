from decomprepair.compound_pair_swap import FAMILY, variants

SOURCE = """void f(Rec *p, s32 count) {
    f32 t;

    t = (f32) count;
    t *= p->rate;
    p->level = (s32) t;
}
"""


def squeezed(text):
    return ''.join(text.split())


def test_the_pair_is_exchanged_and_also_joined():
    children = variants(SOURCE, 'f')
    assert [family for family, _ in children] == [FAMILY, FAMILY]
    assert 't=p->rate;t*=(f32)count;' in squeezed(children[0][1])
    assert 't=(p->rate)*((f32)count);' in squeezed(children[1][1])


def test_only_float_locals_and_operands_that_commute():
    assert variants(SOURCE.replace('f32 t;', 's32 t;'), 'f') == []
    assert variants(SOURCE.replace('t *= p->rate;', 't -= p->rate;'), 'f') == []
    assert variants(SOURCE.replace('t *= p->rate;', 't *= t;'), 'f') == []
    assert variants(SOURCE.replace('t *= p->rate;', 't *= g();'), 'f') == []
    assert variants(SOURCE.replace('t *= p->rate;', 't *= 0.5;'), 'f') == []
    assert variants(SOURCE.replace('t *= p->rate;', 't *= (double) p->rate;'), 'f') == []
    assert variants(SOURCE.replace('f32 t;', 'volatile f32 t;'), 'f') == []


def test_every_pair_is_also_exchanged_together():
    two = SOURCE.replace('    p->level', '    t = p->base;\n    t += p->add;\n    p->level')
    children = variants(two, 'f')
    assert len(children) == 5
    assert 't=p->rate;t*=(f32)count;t=p->add;t+=p->base;' in squeezed(children[0][1])
