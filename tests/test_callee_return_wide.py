"""A callee declared with a narrow return whose result the caller only tests: written as `s32`."""
from decomprepair import callee_prototype_repairs as protos

CODE = '''char test(int, int);
u8 stat(int);
void note(int);
void f(int a)
{
  if (test(a, 2) == 0)
  {
    note(a);
  }
  stat(a);
}
'''


def found(text):
    return [source for family, source in protos.variants(text, 'f') if family == 'callee_return_wide']


def test_a_tested_narrow_result_is_offered_as_an_int_return():
    [source] = [s for s in found(CODE) if 's32 test' in s]
    assert 's32 test(int, int);' in source
    assert 'u8 stat(int);' in source


def test_a_result_nobody_reads_is_left_narrow():
    assert not any('s32 stat' in source for source in found(CODE))


def test_an_assigned_result_counts_as_used():
    code = CODE.replace('stat(a);', 'k = stat(a);')
    assert any('s32 stat(int);' in source for source in found(code))


def test_an_unsigned_int_return_is_offered_for_a_shifted_result():
    code = 'u16 rnd();\nvoid f(short *p)\n{\n  *p = (rnd(0x7FFF) >> 9) - 0x20;\n}\n'
    sources = found(code)
    assert any('u32 rnd();' in source for source in sources)
    assert any('s32 rnd();' in source for source in sources)


def test_m2c_preamble_does_not_hide_the_prototypes():
    code = '#ifndef M2C_DEFINES\n#define M2C_DEFINES\n#endif\n\nu16 rnd();\nvoid f(short *p)\n{\n  *p = (rnd(0x7FFF) >> 9) - 0x20;\n}\n'
    assert any('u32 rnd();' in source for source in found(code))
