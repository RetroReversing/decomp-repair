import pytest

from decomprepair import relocated_global_update as repair

TARGET = '''
/* 00 80001000 3C028003 */ lui $v0, %hi(arena + 0x40)
/* 04 80001004 8C429120 */ lw $v0, %lo(arena + 0x40)($v0)
/* 08 80001008 3C032123 */ lui $v1, (0x21234567 >> 16)
/* 0C 8000100C 34634567 */ ori $v1, $v1, (0x21234567 & 0xFFFF)
/* 10 80001010 00430018 */ mult $v0, $v1
/* 14 80001014 00001012 */ mflo $v0
/* 18 80001018 24430017 */ addiu $v1, $v0, 23
/* 1C 8000101C 24420018 */ addiu $v0, $v0, 24
/* 20 80001020 00021243 */ sra $v0, $v0, 9
/* 24 80001024 3C018003 */ lui $at, %hi(arena + 0x40)
/* 28 80001028 AC239120 */ sw $v1, %lo(arena + 0x40)($at)
/* 2C 8000102C 03E00008 */ jr $ra
/* 30 80001030 304203FF */ andi $v0, $v0, 0x3ff
'''
DRAFT = '''
extern M2C_UNK arena;
s32 update(void) {
    s32 product;
    product = M2C_FIELD(&arena, s32 *, 0x40) * 0x21234567;
    M2C_FIELD(&arena, s32 *, 0x40) = (s32) (product + 23);
    return ((s32) (product + 24) >> 9) & 0x3ff;
}
'''
SYMBOLS = {'arena': 0x800290E0, 'D_80029120': 0x80029120}


def test_recover_direct_word_for_both_relocations():
    candidate = repair.rewrite(DRAFT, 'update', TARGET, resolve=SYMBOLS.get)
    assert candidate == DRAFT.replace('s32 update', 'extern s32 D_80029120;\n\ns32 update').replace(
        'M2C_FIELD(&arena, s32 *, 0x40)', 'D_80029120')


@pytest.mark.parametrize('target', [
    TARGET.replace('8C429120', '8C429124'),
    TARGET.replace('AC239120', 'AC239124'),
    TARGET.replace('sra $v0', 'srl $v0'),
])
def test_reject_different_raw_addresses_or_return_shift(target):
    assert repair.rewrite(DRAFT, 'update', target, resolve=SYMBOLS.get) is None


def test_reject_incompatible_source_or_owned_alias():
    assert repair.rewrite(DRAFT.replace('+ 24', '+ 25'), 'update', TARGET, resolve=SYMBOLS.get) is None
    assert repair.rewrite(DRAFT, 'update', TARGET, 'extern volatile s32 D_80029120;', SYMBOLS.get) is None
