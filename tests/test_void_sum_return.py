from decomprepair import registry
from decomprepair.void_sum_return import FAMILY_ACCUMULATE, FAMILY_RETURN, REPAIR, variants

SOURCE = """void load(s32 arg0)
{
  void *temp;
  fill(arg0, 4);
  G_END = arg0 + 0x300;
  copy(G_END, temp, 0x80);
}
"""
ASM = """/* 0 */  jal        copy
/* 4 */  addiu      $a2, $zero, 0x80
/* 8 */  addiu      $v0, $s0, 0x80
/* c */  lw         $ra, 0x18($sp)
/* 10 */  jr         $ra
/* 14 */  nop
"""


def kids(source=SOURCE, family=None, asm=ASM, header=''):
    return [c for f, c in variants(source, 'load', asm=asm, header=header) if family in (None, f)]


def test_the_stored_sum_advances_the_parameter():
    child = kids(family=FAMILY_ACCUMULATE)[0]
    assert 'arg0 += 0x300;\n  G_END = arg0;\n  copy(arg0, temp, 0x80);' in child
    assert child.startswith('void load')


def test_a_void_function_that_returns_a_sum_widens_and_returns_it():
    child = kids(family=FAMILY_RETURN)[0]
    assert child.startswith('s32 load(s32 arg0)')
    assert 'arg0 += 0x300;' in child
    assert child.rstrip().endswith('return 0x80 + arg0;\n}')


def test_the_stored_variable_is_the_other_child():
    assert any('return 0x80 + G_END;' in c and 'void' not in c.split('(')[0] for c in kids(family=FAMILY_RETURN))


def test_nothing_widens_without_the_targets_return_sum():
    assert not kids(family=FAMILY_RETURN, asm='jr $ra\nnop\n')
    assert not kids(family=FAMILY_RETURN, asm='jal f\naddiu $v0, $zero, 5\njr $ra\nnop\n')
    assert kids(family=FAMILY_ACCUMULATE, asm='')


def test_a_header_prototype_or_an_existing_return_stops_the_widening():
    assert not kids(family=FAMILY_RETURN, header='void load(s32 arg0);')
    assert not kids(SOURCE.replace('  copy(G_END, temp, 0x80);', '  copy(G_END, temp, 0x80);\n  return;'), FAMILY_RETURN)


def test_a_later_write_of_the_sum_or_the_parameter_is_left_alone():
    assert not kids(SOURCE.replace('  copy(', '  G_END = 0;\n  copy('), FAMILY_ACCUMULATE)
    assert not kids(SOURCE.replace('  copy(', '  arg0 = 0;\n  copy('), FAMILY_ACCUMULATE)


def test_the_module_declares_itself():
    assert REPAIR['families'] == (FAMILY_ACCUMULATE, FAMILY_RETURN)
    assert registry.problems(registry.get('void_sum_return')) == []
