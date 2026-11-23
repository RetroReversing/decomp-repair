"""A value set before an `if`/`else` whose else arm overwrites it: set inside the then arm."""
from decomprepair.arm_value_sink import FAMILY, variants

SAVED = '''void f(s32 *out, Spr *r)
{
  s32 s, dsdx;
  dsdx = r->k;
  s = r->w << 5;
  if (r->flags & 0x80)
    dsdx = ~dsdx;
  else
    s = 0;
  out[0] = s;
  out[1] = dsdx;
}
'''


def _squash(text):
    return ' '.join(text.split())


def _children(source):
    return [_squash(src) for fam, src in variants(source, 'f') if fam == FAMILY]


def test_the_value_moves_into_the_then_arm():
    out = _children(SAVED)
    assert len(out) == 1
    assert 'dsdx = r->k; if (r->flags & 0x80) { s = r->w << 5; dsdx = ~dsdx; } else s = 0; out[0] = s;' in out[0]


def test_braced_arms_are_handled():
    source = SAVED.replace('if (r->flags & 0x80)\n    dsdx = ~dsdx;\n  else\n    s = 0;',
                           'if (r->flags & 0x80)\n  {\n    dsdx = ~dsdx;\n  }\n  else\n  {\n    s = 0;\n  }')
    out = _children(source)
    assert len(out) == 1
    assert 'if (r->flags & 0x80) { s = r->w << 5; dsdx = ~dsdx; } else { s = 0; }' in out[0]


def test_a_call_in_the_value_or_the_test_gives_no_child():
    assert _children(SAVED.replace('r->w << 5', 'g(r->w)')) == []
    assert _children(SAVED.replace('r->flags & 0x80', 'g(r) & 0x80')) == []


def test_a_then_arm_that_reads_the_value_or_an_else_that_sets_another_variable_gives_no_child():
    assert _children(SAVED.replace('dsdx = ~dsdx;', 'dsdx = s;')) == []
    assert _children(SAVED.replace('s = 0;\n  out', 'dsdx = 0;\n  out')) == []


def test_no_else_no_child():
    assert _children(SAVED.replace('  else\n    s = 0;\n', '')) == []
