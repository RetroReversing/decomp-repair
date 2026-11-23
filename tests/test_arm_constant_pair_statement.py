"""A scale factor set before the `if`/`else` that picks its sibling: set in both arms."""
from decomprepair.arm_constant_pair import FAMILY_STATEMENT, variants

SAVED = '''void f(s32 *out, Spr *p)
{
  s32 dsdx, dtdy;
  dsdx = 0x400;
  if (hires != 0)
    dtdy = 0x200;
  else
    dtdy = 0x400;
  dsdx = dsdx * p->w / p->cw;
  dtdy = dtdy * p->h / p->ch;
  out[0] = dsdx;
  out[1] = dtdy;
}
'''


def _squash(text):
    return ' '.join(text.split())


def _children(source):
    return [_squash(src) for fam, src in variants(source, 'f') if fam == FAMILY_STATEMENT]


def test_the_constant_is_set_in_both_arms():
    out = _children(SAVED)
    assert len(out) == 1
    assert 'if (hires != 0) { dsdx = 0x400; dtdy = 0x200; } else { dsdx = 0x400; dtdy = 0x400; } dsdx = dsdx * p->w / p->cw;' in out[0]
    assert out[0].count('dsdx = 0x400;') == 2


def test_braced_arms_and_a_condition_with_calls_are_handled():
    source = SAVED.replace('if (hires != 0)\n    dtdy = 0x200;\n  else\n    dtdy = 0x400;',
                           'if (g(1) & 2) { dtdy = 0x200; } else { dtdy = 0x400; }')
    out = _children(source)
    assert len(out) == 1
    assert 'if (g(1) & 2) { dsdx = 0x400; dtdy = 0x200; } else { dsdx = 0x400; dtdy = 0x400; }' in out[0]


def test_a_constant_nothing_reads_later_is_left_alone():
    source = SAVED.replace('dsdx = dsdx * p->w / p->cw;', 'dsdx = 7;').replace('out[0] = dsdx;', 'out[0] = 1;')
    # `dsdx` is still read later in `dsdx = 7`? no: it is only written, so nothing reads the first value.
    assert _children(source.replace('dsdx = 7;', 'dtdy = 7;').replace('dsdx, dtdy', 'dtdy')) == []


def test_arms_that_set_different_variables_or_a_condition_that_reads_the_constant_give_no_child():
    assert _children(SAVED.replace('dtdy = 0x400;', 'dsdx = 0x400;')) == []
    assert _children(SAVED.replace('hires != 0', 'dsdx != 0')) == []
