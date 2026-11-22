from decomprepair.float_register_argument_repairs import FAMILY, float_calls, variants

ASM = '''glabel f
/* 000000 80000000 3C014270 */  lui        $at, 0x4270
/* 000004 80000004 44816000 */  mtc1       $at, $f12
/* 000008 80000008 0C000100 */  jal        step
/* 00000C 8000000C 00000000 */   nop
/* 000010 80000010 03E00008 */  jr         $ra
'''

SOURCE = '''extern void step();
void f(void)
{
    step();
}
'''


def test_the_constant_the_target_puts_in_f12_becomes_the_argument():
    assert float_calls(ASM) == {'step': [0x42700000]}
    texts = [text for family, text in variants(SOURCE, 'f', ASM) if family == FAMILY]
    assert texts == [SOURCE.replace('step();\nvoid', 'step(f32);\nvoid').replace('    step();', '    step(60.0f);')]


def test_splat_spellings_are_read():
    splat = ASM.replace('0x4270', '(0x42700000 >> 16)').replace('$f12', '$fa0')
    assert float_calls(splat) == {'step': [0x42700000]}


def test_a_call_that_already_passes_something_is_left_alone():
    assert not variants(SOURCE.replace('    step();', '    step(1);'), 'f', ASM)


def test_the_target_must_load_a_constant_before_each_call():
    assert not variants(SOURCE, 'f', ASM.replace('mtc1       $at, $f12', 'mtc1       $at, $f14'))
