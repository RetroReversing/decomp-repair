"""A store through a pointer variable as a member of a one-member record, beside a plain global's read.

Synthetic shape of the head of a mixing-buffer function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): the half a
global pointer addresses is cleared and a limit global is compared right after it. The exact-judge replay is in
decompdecomp's tests (it needs the compiler): 1680 -> 1610 on the 370-instruction function."""
from decomprepair import deref_member_store as m
from decomprepair import registry

SOURCE = '''typedef short s16;
typedef unsigned short u16;
extern s16 *D_Buf;
extern u16 D_Limit;
extern s16 D_Other;
void mix(u16 limit)
{
  u16 *count;
  count = 0;
  *D_Buf = 0;
  if (D_Limit != limit)
  {
    D_Other = 1;
  }
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'mix')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_store_becomes_a_member_of_a_one_member_record():
    [text] = texts()
    assert 'typedef struct { s16 value; } __repair_deref_s16;' in text
    assert '(((__repair_deref_s16 *) D_Buf)->value) = 0;' in text
    assert text.index('typedef struct') < text.index('void mix')
    assert '  *D_Buf = 0;' not in text


def test_a_store_far_from_any_global_read_is_left_alone():
    far = SOURCE.replace('  if (D_Limit != limit)', '  count = 0;\n' * 7 + '  if (D_Limit != limit)')
    assert texts(far) == []


def test_a_call_between_the_store_and_the_read_stops_it():
    assert texts(SOURCE.replace('  if (D_Limit', '  if (D_Limit').replace('  *D_Buf = 0;\n', '  *D_Buf = 0;\n  return;\n')) == []


def test_every_qualifying_store_is_one_child_and_all_together_another():
    two = SOURCE.replace('  *D_Buf = 0;\n', '  *D_Buf = 0;\n  *count = 0;\n')
    found = texts(two)
    assert len(found) >= 2
    assert any(t.count('->value') == 2 for t in found)
    assert any(t.count('->value') == 1 for t in found)


def test_a_second_run_does_not_stack_typedefs():
    [text] = texts()
    assert m.variants(text, 'mix') == []


def test_it_declares_itself_to_the_registry():
    assert registry.declared()
    assert any(r.module == 'deref_member_store' for r in registry.declared())
