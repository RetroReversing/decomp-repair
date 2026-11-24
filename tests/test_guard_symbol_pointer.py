"""A guarded loop's table read through a pointer the guard sets, and a table alias as one pointer set in each guard."""
from decomprepair import registry
from decomprepair.guard_symbol_pointer import ALIAS_FAMILY, FAMILY, variants

# A canonical-code builder's code-assignment pass (KMC GCC 2.7.2, N64): the inner test reads the length table.
ASSIGN = '''extern u32 D_800B283C[];
extern u32 D_800B2CB8[];
void f(u32 c)
{
  u32 i;
  u32 k;
  k = 0;
  do {
    if (D_800B283C[k] == c) {
      u32 hb = 1 << c;
      do {
        D_800B2CB8[k] = i | hb;
        i++;
        k++;
      } while (D_800B283C[k] == c);
    }
    c++;
  } while (c < 16);
}
'''

# Three passes that bound their loops through a long-lived alias of the histogram.
ALIAS = '''extern u32 D_80112EE0[];
void f(u32 *out)
{
  u32 *H;
  u32 c;
  u32 i;
  H = D_80112EE0;
  for (c = 1; c < 16; c++) {
    i = 1;
    if (H[c] != 0) {
      u32 *lim = (u32 *)((char *)H + c * 4);
      do {
        *out++ = c;
        i++;
      } while (*lim >= i);
    }
  }
  for (c = 1; c < 16; c++) {
    i = 1;
    if (H[c] != 0) {
      u32 *lim = (u32 *)((char *)H + c * 4);
      do {
        *out++ = i;
        i++;
      } while (*lim >= i);
    }
  }
}
'''


def _children(text, family):
    return [src for fam, src in variants(text, 'f') if fam == family]


def test_the_inner_test_reads_a_pointer_declared_after_the_guards_declarations():
    want = ASSIGN.replace('      u32 hb = 1 << c;\n', '      u32 hb = 1 << c;\n      u32 *tp = D_800B283C;\n').replace(
        'while (D_800B283C[k] == c)', 'while (tp[k] == c)')
    kids = _children(ASSIGN, FAMILY)
    assert want in kids
    assert ASSIGN.replace('      u32 hb = 1 << c;\n', '      u32 *tp = D_800B283C;\n      u32 hb = 1 << c;\n').replace(
        'while (D_800B283C[k] == c)', 'while (tp[k] == c)') in kids


def test_the_alias_becomes_one_pointer_set_in_each_guard():
    kids = _children(ALIAS, ALIAS_FAMILY)
    both = ALIAS.replace('  u32 *H;\n', '  u32 *gp;\n  u32 *H;\n').replace(
        'u32 *lim = (u32 *)((char *)H + c * 4);', 'u32 *lim; gp = D_80112EE0; lim = (u32 *)((char *)gp + c * 4);')
    assert kids[0] == both
    assert len(kids) == 3  # both guards, and each alone
    assert all(kid.count('gp = D_80112EE0;') == 1 for kid in kids[1:])


def test_a_table_the_source_does_not_declare_is_left_alone():
    assert _children(ASSIGN.replace('extern u32 D_800B283C[];\n', ''), FAMILY) == []


def test_volatile_is_left_alone():
    assert variants(ASSIGN.replace('u32 i;', 'volatile u32 i;'), 'f') == []


def test_an_alias_set_twice_is_left_alone():
    text = ALIAS.replace('  for (c = 1; c < 16; c++) {\n    i = 1;\n    if (H[c] != 0) {\n      u32 *lim = (u32 *)((char *)H + c * 4);\n      do {\n        *out++ = i;',
                         '  H = out;\n  for (c = 1; c < 16; c++) {\n    i = 1;\n    if (H[c] != 0) {\n      u32 *lim = (u32 *)((char *)H + c * 4);\n      do {\n        *out++ = i;')
    assert _children(text, ALIAS_FAMILY) == []


def test_it_declares_itself():
    assert any(r.module.endswith('guard_symbol_pointer') for r in registry.declared())
