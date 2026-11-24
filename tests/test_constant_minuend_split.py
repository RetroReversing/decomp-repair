"""constant_minuend_split: `c - (call() + k)` as a constant local set before an early return and a sum local."""
from decomprepair import constant_minuend_split as cms
from decomprepair import registry

NAME = 'func_80030000'
SOURCE = '''s32 func_80031000(s32);                             /* extern */

s32 func_80030000(s32 arg0) {
    if (arg0 == 0) {
        return 0;
    }
    return 0x2A - (func_80031000(arg0) + 3);
}
'''
ASM = '''
glabel func_80030000
    /* 0 */  addiu      $sp, $sp, -0x18
    /* 4 */  beqz       $a0, .L24
    /* 8 */   sw        $ra, 0x14($sp)
    /* c */  jal        func_80031000
    /* 10 */   addiu    $v1, $zero, 0x2A
    /* 14 */  addiu     $v0, $v0, 0x3
    /* 18 */  subu      $v0, $v1, $v0
    /* 1c */  b         .L28
    /* 20 */   nop
.L24:
    /* 24 */  move      $v0, $zero
.L28:
    /* 28 */  lw        $ra, 0x14($sp)
    /* 2c */  jr        $ra
    /* 30 */   addiu    $sp, $sp, 0x18
endlabel func_80030000
'''


def _children(source=SOURCE, asm=ASM, **kw):
    return cms.variants(source, NAME, asm=asm, **kw)


def test_the_target_builds_the_constant_after_the_call_and_subtracts_the_stepped_result():
    assert cms.evidence(ASM) == {(0x2A, 3)}
    assert _children(asm='') == []
    assert _children(asm=ASM.replace('0x2A', '0x2B')) == []  # (another constant)
    assert _children(asm=ASM.replace('addiu     $v0, $v0, 0x3', 'addiu     $v0, $v0, 0x4')) == []  # (another step)
    before = ASM.replace('/* c */  jal        func_80031000\n    /* 10 */   addiu    $v1, $zero, 0x2A',
                         '/* c */  addiu      $v1, $zero, 0x2A\n    /* 10 */  jal        func_80031000')
    assert cms.evidence(before) == set()  # (built before the call: the folded form compiles that way)


def test_the_constant_is_set_before_the_early_return_and_the_sum_is_a_local():
    text = dict(_children())[cms.FAMILY]
    assert 's32 minuend_c;\n    s32 minuend_sum;' in text
    assert 'minuend_c = 0x2A;\n    if (arg0 == 0) {' in text
    assert 'minuend_sum = func_80031000(arg0) + 3;\n    return minuend_c - minuend_sum;' in text
    assert '0x2A - (' not in text


def test_a_leading_statement_gives_the_head_form_and_a_difference_can_be_stored():
    source = SOURCE.replace('    if (arg0 == 0)', '    arg0 += 1;\n    if (arg0 == 0)').replace('s32 func_80030000(s32 arg0) {\n', 's32 func_80030000(s32 arg0) {\n    s32 temp_v0;\n')
    source = source.replace('return 0x2A - (func_80031000(arg0) + 3);', 'temp_v0 = 0x2A - (func_80031000(arg0) - -3);').replace('- -3', '+ 3') + ''
    text = dict(_children(source))
    assert 'minuend_c = 0x2A;\n    arg0 += 1;' in text[cms.HEAD_FAMILY]
    assert 'temp_v0 = minuend_c - minuend_sum;' in text[cms.FAMILY]


def test_a_minus_step_and_an_unsigned_call():
    minus = SOURCE.replace('+ 3', '- 3')
    assert not _children(minus)
    both = _children(minus, ASM.replace('0x3', '-0x3'))
    assert 'minuend_sum = func_80031000(arg0) - 3;' in dict(both)[cms.FAMILY]
    unsigned = SOURCE.replace('s32 func_80031000(s32);', 'u32 func_80031000(s32);')
    assert 'u32 minuend_c;' in dict(_children(unsigned))[cms.FAMILY]


def test_declines_what_is_not_the_shape():
    assert _children(SOURCE.replace('    if (arg0 == 0) {\n        return 0;\n    }\n', '')) == []  # (no earlier branch)
    assert _children(SOURCE.replace('    if (arg0 == 0) {\n        return 0;\n    }\n', '    arg0 += 1;\n')) == []
    assert _children(SOURCE.replace('s32 func_80031000(s32);', 'void func_80031000(s32);')) == []  # (no integer result)
    assert _children(SOURCE.replace('0x2A - (func_80031000(arg0) + 3)', '0x2A - func_80031000(arg0)')) == []
    assert _children(SOURCE.replace('func_80031000(arg0) + 3', 'arg0 + 3')) == []  # (no call)


def test_registered_and_needs_the_assembly():
    found = {r.module: r for r in registry.declared()}['constant_minuend_split']
    assert set(found.families) == set(cms.FAMILIES) and 'asm' in found.needs
