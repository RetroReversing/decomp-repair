"""The operands of an assignment's sum or difference written the other way round when both make a call."""
from decomprepair.call_operand_eval_order import FAMILY, variants

SRC = '''s32 f(Rec *p, f32 dx, f32 dz)
{
    f32 t;
    t = ((s32)(dx * sins(-p->a)) >> 15) + ((s32)(dz * coss(-p->a)) >> 15);
    dz = ((s32)(dz * sins(-p->a)) >> 15) - ((s32)(dx * coss(-p->a)) >> 15);
    dx = p->x - p->y;
    dx = g(1) - 2.0e-3f;
    return t * h(dz);
}
'''


def kids():
    return [src for fam, src in variants(SRC, 'f') if fam == FAMILY]


def test_difference_of_two_calls_puts_the_second_call_first():
    # the rotation's second row, called cosine first in the target (a 1585-instruction collision routine)
    want = SRC.replace(
        'dz = ((s32)(dz * sins(-p->a)) >> 15) - ((s32)(dx * coss(-p->a)) >> 15);',
        'dz = -(((s32)(dx * coss(-p->a)) >> 15)) + ((s32)(dz * sins(-p->a)) >> 15);')
    assert want in kids()


def test_sum_of_two_calls_is_commuted():
    want = SRC.replace(
        't = ((s32)(dx * sins(-p->a)) >> 15) + ((s32)(dz * coss(-p->a)) >> 15);',
        't = ((s32)(dz * coss(-p->a)) >> 15) + ((s32)(dx * sins(-p->a)) >> 15);')
    assert want in kids()


def test_operands_without_two_calls_are_left_alone():
    # `p->x - p->y` has no call, `g(1) - 2.0e-3f` one; a return is not an assignment
    assert len(kids()) == 2


def test_member_arrows_and_unary_minus_are_not_operators():
    src = 'void f(Obj *o)\n{\n    o->v = -g(o->a) - h(o->b);\n}\n'
    out = [s for fam, s in variants(src, 'f') if fam == FAMILY]
    assert out == ['void f(Obj *o)\n{\n    o->v = -(h(o->b)) + -g(o->a);\n}\n']
