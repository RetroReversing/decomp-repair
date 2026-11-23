"""`v = e; w = v;` written `w = e;` when nothing reads `v` again.

Synthetic shape of the mixing function's limit relay (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`). The exact-judge replay
is in decompdecomp's tests (it needs the compiler): the fold took 1610 -> 1565 beside the member store."""
from decomprepair import registry
from decomprepair import relay_copy_fold as m

SOURCE = '''typedef unsigned int u32;
typedef int s32;
extern int g_limit;
void walk(int a)
{
  s32 relay;
  u32 limit;
  s32 count;
  relay = a & 0xFFFF;
  limit = relay;
  count = relay;
  relay = 0;
  step(limit, relay, count);
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'walk')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_a_relay_read_again_is_kept():
    assert texts() == []  # `count = relay;` reads it after the pair


def test_the_relay_folds_when_every_later_use_is_an_assignment():
    source = SOURCE.replace('  count = relay;\n', '  count = 1;\n')
    [text] = texts(source)
    assert '  limit = a & 0xFFFF;\n' in text
    assert 'relay = a & 0xFFFF;' not in text
    assert '  relay = 0;' in text


def test_an_expression_with_a_call_is_not_folded():
    source = SOURCE.replace('  count = relay;\n', '  count = 1;\n').replace('a & 0xFFFF', 'read(a)')
    assert texts(source) == []


def test_it_declares_itself_to_the_registry():
    assert any(r.module == 'relay_copy_fold' for r in registry.declared())
