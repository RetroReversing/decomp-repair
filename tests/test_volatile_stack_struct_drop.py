"""A hand-written `volatile struct` frame with `#define` member names, written as plain locals."""
import re

from decomprepair import registry
from decomprepair.volatile_stack_struct_drop import FAMILY, variants

CODE = '''typedef int s32;
typedef unsigned char u8;
extern void g(s32);

void f(void *arg0, s32 arg1, s32 arg2)
{
  volatile struct { int unused; int filter; } stack;
#define sp14 stack.filter
  u8 sp1F;
  s32 i;
  sp14 = arg2;
  sp1F = 1;
  for (i = 0; i < arg1; i++)
  {
    if (sp14 == i)
    {
      g(sp1F);
    }
  }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_volatile_frame_becomes_a_plain_local_of_the_member_type():
    [(family, child)] = variants(CODE, 'f')
    text = squash(child)
    assert family == FAMILY
    assert 'volatile' not in text and '#define' not in text and 'stack' not in text
    assert 'int sp14; u8 sp1F;' in text
    assert 'sp14 = arg2;' in text and 'sp14 == i' in text
    assert 'unused' not in text


def test_a_member_read_without_a_name_gets_a_local_of_its_own():
    code = CODE.replace('sp14 = arg2;', 'stack.filter = arg2;').replace('#define sp14 stack.filter\n', '')
    [(_, child)] = variants(code, 'f')
    text = squash(child)
    assert 'int stack_filter; u8 sp1F;' in text
    assert 'stack_filter = arg2;' in text


def test_an_address_taken_frame_or_a_name_used_elsewhere_is_left_alone():
    assert variants(CODE.replace('g(sp1F);', 'g(&stack);'), 'f') == []
    assert variants(CODE.replace('extern void g(s32);', 'extern void g(s32);\nextern s32 sp14;'), 'f') == []
    assert variants(CODE.replace('int unused;', 'int unused[2];'), 'f') == []
    assert variants('void h(void)\n{\n  int x;\n  x = 1;\n}\n', 'h') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []


def test_it_declares_that_it_reads_the_functions_own_directives():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert repair.directives is True
    assert not any(item.directives for item in registry.declared() if item.module == 'pair_pointer_struct')
