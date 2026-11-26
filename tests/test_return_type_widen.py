"""A narrow return type the target never narrows to, written as the word it returns."""
import re

from decomprepair import registry
from decomprepair.return_type_widen import FAMILY, FAMILY_TYPE, variants

CODE = '''extern char tab_a[];
extern char tab_b[];

u16 lookup(s32 arg0) {
    s32 temp_a0;

    temp_a0 = arg0 & 0xFFF;
    if (temp_a0 < 0x400) {
        return *(u16 *)(tab_a + ((0x400 - temp_a0) * 2));
    }
    if (temp_a0 < 0x800) {
        return (u16) -(s32) *(u16 *)(tab_b + (temp_a0 * 2));
    }
    return (u16) (temp_a0 + 1);
}
'''
PLAIN_ASM = '''glabel lookup
/* 0 0 30840FFF */  andi       $a0, $a0, 0xFFF
/* 4 4 00021023 */  negu       $v0, $v0
/* 8 8 03E00008 */  jr         $ra
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_type_and_the_covering_casts_come_together_first_then_the_type_alone():
    out = variants(CODE, 'lookup', PLAIN_ASM)
    assert [f for f, _ in out] == [FAMILY, FAMILY_TYPE]
    both, only = (squash(t) for _, t in out)
    assert 's32 lookup(s32 arg0)' in both and 's32 lookup(s32 arg0)' in only
    assert 'return -(s32) *(u16 *)(tab_b + (temp_a0 * 2));' in both
    assert 'return (u16) (temp_a0 + 1);' not in both and 'return (temp_a0 + 1);' in both
    assert 'return (u16) -(s32)' in only


def test_a_cast_over_only_the_first_operand_stays():
    code = CODE.replace('return (u16) (temp_a0 + 1);', 'return (u16) temp_a0 + 1;')
    both = squash(variants(code, 'lookup', PLAIN_ASM)[0][1])
    assert 'return (u16) temp_a0 + 1;' in both


def test_a_target_that_narrows_gets_nothing():
    masked = PLAIN_ASM + '/* c c 3042FFFF */  andi       $v0, $v0, 0xFFFF\n'
    assert variants(CODE, 'lookup', masked) == []
    shifted = PLAIN_ASM + '/* c c 00021400 */  sll        $v0, $v0, 16\n'
    assert variants(CODE, 'lookup', shifted) == []
    assert variants(CODE, 'lookup', '') == []


def test_a_word_return_a_header_prototype_and_other_functions_are_left_alone():
    assert variants(CODE.replace('u16 lookup', 's32 lookup'), 'lookup', PLAIN_ASM) == []
    assert variants(CODE, 'lookup', PLAIN_ASM, header='extern u16 lookup(s32 a);') == []
    assert variants(CODE, 'missing', PLAIN_ASM) == []


def test_a_prototype_in_the_source_changes_with_the_definition():
    code = 'u8 pick(s32 a);\n' + 'u8 pick(s32 a) {\n    return (u8) a;\n}\n'
    both = variants(code, 'pick', PLAIN_ASM)[0][1]
    assert both.count('s32 pick(s32 a)') == 2 and 'return a;' in squash(both)


def test_it_is_declared_for_every_caller():
    declared = {repair.module: repair for repair in registry.declared()}
    assert set(declared['return_type_widen'].families) == {FAMILY, FAMILY_TYPE}
