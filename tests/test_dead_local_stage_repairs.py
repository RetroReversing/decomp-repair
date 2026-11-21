"""An operand held in a local that is dead at the statement."""
from decomprepair import dead_local_stage_repairs as r

SOURCE = '''void f(void)
{
  void *n;
  void *m;
  s32 a;
  s32 rv;
  s32 h;
  s32 g;
  u32 j;
  j = 0;
  do
  {
    rv = h1();
    D_1 = rv;
    n = D_800EDA8C;
    m = *((void **) (((char *) n) + 0x6C));
    a = *((s32 *) (((char *) m) + 4));
    k(a);
    g = (*((u16 *) (((char *) n) + 0xFC2))) * ((n->value * 3) >> 3);
    h = *((s32 *) (((char *) n) + 0x70));
    *((s32 *) (((char *) n) + 0x74)) += (h >> 16) + (*((u32 *) (((char *) n) + 0x11C)));
    j++;
  }
  while (j < 8);
}
'''


def staged(source, local, operand):
    return [t for _, t in r.variants(source, 'f') if f'{local} = {operand}' in t]


def test_a_factor_in_the_call_result_local():
    # A sequencer's product register: the factor lived in the call-result local, dead after its store (60 -> 20 -> 0).
    (out,) = staged(SOURCE, 'rv', '((n->value * 3) >> 3);')
    assert 'rv = ((n->value * 3) >> 3); g = (*((u16 *) (((char *) n) + 0xFC2))) * rv;' in out


def test_a_load_in_the_loops_pointer_local():
    out = [t for t in staged(SOURCE, 'm', '(void *) (*((u32 *) (((char *) n) + 0x11C)));')]
    (first,) = out
    assert 'm = (void *) (*((u32 *) (((char *) n) + 0x11C))); *((s32 *) (((char *) n) + 0x74)) += (h >> 16) + (u32) m;' in first


def test_a_local_that_is_live_is_left_alone():
    # `a` is read by k(a) before; here it is read after the statement, so it is not offered; `m` is read after too
    after = SOURCE.replace('    j++;\n', '    k(a);\n    j++;\n')
    assert staged(after, 'a', '((n->value * 3) >> 3);') == []
    # a read at the top of the loop reaches the value from the previous lap
    wrapped = SOURCE.replace('    rv = h1();\n', '    k(rv);\n    rv = h1();\n')
    assert staged(wrapped, 'rv', '((n->value * 3) >> 3);') == []
    # the statement's own locals and plain operands
    assert all('g = g' not in t for _, t in r.variants(SOURCE, 'f'))
