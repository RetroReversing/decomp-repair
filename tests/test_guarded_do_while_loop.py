"""A guard over a do-while with the same test, whose block only sets up the loop, as the `while` it was."""
from decomprepair import registry
from decomprepair.guarded_do_while_loop import FAMILY, variants

# A canonical-code builder's code-assignment pass (KMC GCC 2.7.2, N64).
ASSIGN = '''extern u32 D_800B283C[];
void f(u32 c, u32 *out)
{
  u32 i;
  u32 k;
  u32 y;
  do {
    if (D_800B283C[k] == c) {
      u32 hb = 1 << c;
      u32 *tp = D_800B283C;
      do {
        y = i | hb;
        i++;
        out[k] = y;
        k++;
      } while (tp[k] == c);
    }
    i *= 2;
    c++;
  } while (D_800B283C[k] != 0);
}
'''

WANT = '''extern u32 D_800B283C[];
void f(u32 c, u32 *out)
{
  u32 i;
  u32 k;
  u32 y;
  do {
    while (D_800B283C[k] == c) {
      y = i | (1 << c);
      i++;
      out[k] = y;
      k++;
    }
    i *= 2;
    c++;
  } while (D_800B283C[k] != 0);
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_guard_and_its_loop_become_the_while():
    assert _children(ASSIGN) == [WANT]


def test_a_value_the_body_changes_is_left_alone():
    assert _children(ASSIGN.replace('        i++;\n', '        i++;\n        c++;\n')) == []


def test_a_different_loop_test_is_left_alone():
    assert _children(ASSIGN.replace('while (tp[k] == c)', 'while (tp[k] != c)')) == []


def test_a_guard_with_an_else_is_left_alone():
    text = ASSIGN.replace('      } while (tp[k] == c);\n    }\n', '      } while (tp[k] == c);\n    } else {\n      i = 0;\n    }\n')
    assert _children(text) == []


def test_a_break_in_the_body_is_left_alone():
    assert _children(ASSIGN.replace('        out[k] = y;\n', '        out[k] = y;\n        if (y == 0) break;\n')) == []


def test_it_declares_itself():
    assert any(r.module.endswith('guarded_do_while_loop') for r in registry.declared())
