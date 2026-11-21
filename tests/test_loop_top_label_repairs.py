"""A while loop's first load, already made by its own test, kept by a label at the top of the body."""
from decomprepair import loop_top_label_repairs as t

SOURCE = '''void f(void)
{
  void *n;
  void *m;
  n = D_800EDA8C;
  if (D_1 != 0)
  {
    while ((*((u32 *) (((char *) (*((void **) (((char *) n) + 0xF6C)))) + 0))) != (-1U))
    {
      m = *((void **) (((char *) n) + 0xF6C));
      if (((u32) (*((s32 *) (((char *) n) + 0xF74)))) < ((u32) (*((u32 *) (((char *) m) + 0)))))
      {
        break;
      }
      g(m);
      n = D_800EDA8C;
    }
  }
}
'''


def test_the_reload_gets_a_label():
    # A PS-era MIPS function with this loop: 505 and a carried `m`; with the label 230 and the target's reload.
    (family, out), = t.variants(SOURCE, 'f')
    assert family == 'loop_top_label'
    assert '{\n      __repair_loop_top_0: m = *((void **) (((char *) n) + 0xF6C));' in out
    assert out.replace('__repair_loop_top_0: ', '') == SOURCE


def test_m2c_spelling_too():
    source = '''void f(void *arg0) {
    void *var_v0;
    while (M2C_FIELD(M2C_FIELD(arg0, void **, 0x6C), s32 *, 0) != -1) {
        var_v0 = M2C_FIELD(arg0, void **, 0x6C);
        g(var_v0);
    }
}
'''
    (family, out), = t.variants(source, 'f')
    assert '{\n        __repair_loop_top_0: var_v0 = M2C_FIELD(arg0, void **, 0x6C);' in out


def test_left_alone_otherwise():
    # the load isn't in the test, a plain copy, a do/while, a label already there, or no braces
    assert t.variants(SOURCE.replace('0xF6C)))) + 0))) != (-1U))', '0xF70)))) + 0))) != (-1U))'), 'f') == []
    assert t.variants(SOURCE.replace('m = *((void **) (((char *) n) + 0xF6C));', 'm = n;'), 'f') == []
    dowhile = '''void f(void *n) {
    void *m;
    do {
        m = *((void **) (((char *) n) + 0xF6C));
        g(m);
    } while (*((void **) (((char *) n) + 0xF6C)) != 0);
}
'''
    assert t.variants(dowhile, 'f') == []
    assert t.variants(SOURCE.replace('      m = *((void **)', '      top: m = *((void **)'), 'f') == []
    assert t.variants(SOURCE.replace('    {\n      m =', '    \n      m ='), 'f') == []
