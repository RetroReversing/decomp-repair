"""A scale factor held in a variable that the picking `if` also sets."""
from decomprepair.arm_constant_pair import FAMILY, variants

SAVED = '''void f(s32 *out, Spr *p)
{
  s32 dsdx, dtdy;
  dtdy = hires != 0 ? 0x200 : 0x400;
  dsdx = (0x400 * p->w) / p->cw;
  dtdy = (dtdy * p->h) / p->ch;
  out[0] = dsdx;
  out[1] = dtdy;
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_both_factors_are_set_in_both_arms_and_multiplied_from_the_variables():
    out = [_squash(src) for fam, src in variants(SAVED, 'f') if fam == FAMILY]
    assert len(out) == 1
    assert 'if (hires != 0) { dsdx = 0x400; dtdy = 0x200; } else { dsdx = 0x400; dtdy = 0x400; }' in out[0]
    assert 'dsdx = (dsdx * p->w) / p->cw; dtdy = (dtdy * p->h) / p->ch;' in out[0]


def test_a_read_of_the_scaled_local_between_the_two_statements_is_left_alone():
    source = SAVED.replace('dsdx = (0x400', 'g(dsdx);\n  dsdx = (0x400')
    assert variants(source, 'f') == []


def test_no_conditional_no_child():
    assert variants(SAVED.replace('hires != 0 ? 0x200 : 0x400', '0x200'), 'f') == []
