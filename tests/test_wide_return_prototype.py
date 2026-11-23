"""A callee declared to return a 64-bit integer whose results are only ever kept in 32-bit variables."""
from decomprepair import registry
from decomprepair.wide_return_prototype import FAMILY, variants

SOURCE = '''volatile long long sign_of(s32);
s32 poll(void);
extern s32 gSink;
void scan(s32 x)
{
  unsigned int temp;
  s32 w;
  temp = sign_of(x);
  if (temp != gSink)
  {
    gSink = temp;
  }
  w = sign_of(x + 1);
  sign_of(2);
  if (sign_of(3) == 0) { poll(); }
}
'''


def test_the_wide_prototype_becomes_the_word_the_results_are_kept_in():
    # the result of a one-word callee copied out of $v1: the compare operands' registers were off by one (4846 -> 4786)
    found = variants(SOURCE, 'scan')
    assert [family for family, _ in found] == [FAMILY, FAMILY]
    unsigned, signed = (text for _, text in found)
    assert 'u32 sign_of(s32);' in unsigned and 's32 sign_of(s32);' in signed
    assert 'volatile' not in unsigned and 'long long' not in signed and 's32 poll(void);' in signed


def test_a_result_kept_in_a_wide_variable_or_one_nobody_declares_is_left_alone():
    assert variants(SOURCE.replace('  s32 w;', '  long long w;'), 'scan') == []
    assert variants(SOURCE.replace('  s32 w;\n', ''), 'scan') == []
    assert variants(SOURCE.replace('volatile long long', 's32'), 'scan') == []
    assert variants(SOURCE.replace('sign_of(x)', 'other(x)').replace('sign_of(x + 1)', 'other(2)').replace('sign_of(2)', 'other(3)')
                    .replace('sign_of(3)', 'other(4)'), 'scan') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'wide_return_prototype' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'wide_return_prototype':
            assert registry.problems(repair) == []
