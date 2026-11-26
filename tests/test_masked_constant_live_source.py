from decomprepair import registry
from decomprepair.masked_constant_live_source import FAMILY, REPAIR, variants

SOURCE = """void scan(u8 *arg0, u8 *arg1) {
    s32 var_v0;
    s32 var_v1;
    u8 *var_a0;

    var_a0 = arg0;
    var_v1 = 0;
    if (*var_a0 == 0) {
        goto block_7;
    }
loop_1:
    var_a0 += 1;
    if (*var_a0 != 0) {
        goto loop_1;
    }
    var_v0 = 0 & 0xFF;
    goto block_8;
block_7:
    var_v0 = var_v1 & 0xFF;
block_8:
    if (var_v0 == 0) {
        goto loop_1;
    }
    return;
}
"""
ASM = "andi $v0, $v1, 0xff\n"


def kids(source=SOURCE, asm=''):
    return [c for f, c in variants(source, 'scan', asm=asm) if f == FAMILY]


def test_the_folded_zero_becomes_the_live_variable_masked():
    child = kids()[0]
    assert 'var_v0 = var_v1 & 0xFF;\n    goto block_8;' in child
    assert '0 & 0xFF' not in child


def test_the_target_must_have_an_andi_with_that_mask():
    assert kids(asm=ASM)
    assert not kids(asm='move $v0, $zero\n')


def test_a_constant_nobody_set_earlier_is_left_alone():
    assert not kids(SOURCE.replace('var_v1 = 0;', 'var_v1 = 5;'))


def test_the_module_declares_itself():
    assert REPAIR['families'] == (FAMILY,)
    assert registry.problems(registry.get('masked_constant_live_source')) == []
