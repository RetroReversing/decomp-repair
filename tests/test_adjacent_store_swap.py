"""adjacent_store_swap: two adjacent final stores of locals to different globals or fields, in the other order."""
from decomprepair import adjacent_store_swap as ass
from decomprepair import registry

NAME = 'func_80050000'
SOURCE = '''extern s32 D_80100000;
extern s32 D_80100004;

void func_80050000(s32 arg0) {
    s32 temp_s0;
    s32 temp_s1;

    temp_s0 = func_80051000(arg0);
    temp_s1 = func_80052000(arg0);
    D_80100000 = temp_s0;
    D_80100004 = temp_s1;
}
'''
ASM = '''
glabel func_80050000
    /* 40 */  lui       $at, %hi(D_80100000)
    /* 44 */  sw        $s1, %lo(D_80100000)($at)
    /* 48 */  lui       $at, %hi(D_80100004)
    /* 4c */  sw        $s0, %lo(D_80100004)($at)
    /* 50 */  jr        $ra
    /* 54 */   nop
endlabel func_80050000
'''


def _children(source=SOURCE, asm=ASM, **kw):
    return ass.variants(source, NAME, asm=asm, **kw)


def test_the_target_stores_registers_in_the_exchanged_order():
    seen = ass.evidence(ASM)
    assert seen[('sym', 'D_80100000')][1] == '$s1' and seen[('sym', 'D_80100004')][1] == '$s0'
    assert _children(asm='') == []


def test_the_pair_is_swapped():
    [(family, text)] = _children()
    assert family == ass.FAMILY
    assert text.endswith('    D_80100004 = temp_s1;\n    D_80100000 = temp_s0;\n}\n')


def test_a_target_in_the_natural_order_is_left_alone():
    natural = ASM.replace('$s1, %lo(D_80100000)', '$s2, %lo(D_80100000)').replace('$s0, %lo(D_80100004)', '$s3, %lo(D_80100004)')
    assert _children(asm=natural) == []  # (ascending registers in the source's own order)
    flipped = ASM.replace('D_80100000', 'TMP').replace('D_80100004', 'D_80100000').replace('TMP', 'D_80100004').replace('$s1', '$s5').replace('$s0', '$s6')
    assert len(_children(asm=flipped)) == 1  # (stored in the other order than written)
    same = ASM.replace('$s1, %lo(D_80100000)', '$s0, %lo(D_80100000)')
    assert _children(asm=same) == []  # (one register for both: not two locals)
    temporaries = natural.replace('$s2', '$a0').replace('$s3', '$a1')
    assert _children(asm=temporaries) == []  # (argument registers in the source's order: nothing says it is exchanged)
    assert len(_children(asm=flipped.replace('$s5', '$a0').replace('$s6', '$a1'))) == 1  # (stored in the other order: any registers)


def test_only_the_trailing_run_of_stores_of_distinct_locals_and_a_final_return_is_ignored():
    three = SOURCE.replace('    D_80100004 = temp_s1;\n', '    D_80100004 = temp_s1;\n    D_80100008 = temp_s1;\n').replace('extern s32 D_80100004;', 'extern s32 D_80100004;\nextern s32 D_80100008;')
    assert len(_children(three, ASM + '    sw $s1, %lo(D_80100008)($at)\n')) >= 1
    ret = SOURCE.replace('    D_80100004 = temp_s1;\n}', '    D_80100004 = temp_s1;\n    return;\n}')
    assert len(_children(ret)) == 1
    same_value = SOURCE.replace('D_80100004 = temp_s1;', 'D_80100004 = temp_s0;')
    assert _children(same_value) == []
    called = SOURCE.replace('D_80100004 = temp_s1;', 'D_80100004 = foo(temp_s1);')
    assert _children(called) == []
    first = SOURCE.replace('    D_80100000 = temp_s0;\n', '    D_80100000 = temp_s0;\n    foo();\n')
    assert _children(first) == []  # (a call after the pair: it is not the end of the function)


def test_fields_of_one_base_are_swapped_and_a_global_with_a_field_is_not():
    fields = SOURCE.replace('D_80100000 = temp_s0;', 'M2C_FIELD(arg1, s32 *, 0x10) = temp_s0;').replace('D_80100004 = temp_s1;', 'M2C_FIELD(arg1, s32 *, 0x14) = temp_s1;')
    asm = ASM.replace('%lo(D_80100000)($at)', '0x10($a1)').replace('%lo(D_80100004)($at)', '0x14($a1)')
    assert len(_children(fields, asm)) == 1
    other_base = fields.replace('M2C_FIELD(arg1, s32 *, 0x14)', 'M2C_FIELD(arg2, s32 *, 0x14)')
    assert _children(other_base, asm) == []
    mixed = fields.replace('M2C_FIELD(arg1, s32 *, 0x14) = temp_s1;', 'D_80100004 = temp_s1;')
    assert _children(mixed, asm.replace('0x14($a1)', '%lo(D_80100004)($at)')) == []


def test_registered_and_needs_the_assembly():
    found = {r.module: r for r in registry.declared()}['adjacent_store_swap']
    assert set(found.families) == {ass.FAMILY} and 'asm' in found.needs
