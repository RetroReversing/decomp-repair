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


def countdown_asm():
    rows = [
        ('lui $v0, %hi(arena + 64)', 0x3C028003), ('lw $v0, %lo(arena + 64)($v0)', 0x8C429120),
        ('blez $v0, .Lnonpositive', 0x18400005), ('nop', 0),
        ('addiu $v0, $v0, -1', 0x2442FFFF), ('lui $at, %hi(arena + 64)', 0x3C018003),
        ('j .Lend', 0x0800000F), ('sw $v0, %lo(arena + 64)($at)', 0xAC229120),
        ('.Lnonpositive:', None), ('bnez $v0, .Lskip', 0x14400006),
        ('addiu $v0, $zero, -1', 0x2402FFFF), ('lui $v1, %hi(arena + 72)', 0x3C038003),
        ('lw $v1, %lo(arena + 72)($v1)', 0x8C639128), ('lui $at, %hi(arena + 64)', 0x3C018003),
        ('sw $v0, %lo(arena + 64)($at)', 0xAC229120), ('sh $zero, 6($v1)', 0xA4600006),
        ('.Lskip:', None), ('.Lend:', None), ('jr $ra', 0x03E00008), ('nop', 0),
    ]
    lines = []
    address = 0
    for text, word in rows:
        if word is not None:
            text = f'/* {address:X} {address:08X} {word:08X} */ {text}'
            address += 4
        lines.append(text)
    return '\n'.join(lines)


COUNTDOWN = '''
void tick(void) {
    if (M2C_FIELD(&arena, s32 *, 0x40) > 0) {
        M2C_FIELD(&arena, s32 *, 0x40) = (s32) (M2C_FIELD(&arena, s32 *, 0x40) - 1);
        return;
    }
    if (M2C_FIELD(&arena, s32 *, 0x40) == 0) {
        M2C_FIELD(&arena, s32 *, 0x40) = -1;
        M2C_FIELD(M2C_FIELD(&arena, void **, 0x48), s16 *, 6) = 0;
    }
    update();
}
'''


def test_countdown_keeps_other_stores_and_control_flow():
    asm = countdown_asm()
    candidate = repair.rewrite_countdown(COUNTDOWN, 'tick', asm, resolve=SYMBOLS.get)
    assert candidate == COUNTDOWN.replace('void tick', 'extern s32 D_80029120;\n\nvoid tick').replace(
        'M2C_FIELD(&arena, s32 *, 0x40)', 'D_80029120')


def test_countdown_requires_both_raw_store_relocations():
    asm = countdown_asm()
    assert repair.rewrite_countdown(COUNTDOWN, 'tick', asm.replace('AC229120', 'AC229124', 1),
                                    resolve=SYMBOLS.get) is None
    assert repair.rewrite_countdown(COUNTDOWN.replace('s16 *, 6', 's16 *, 8'), 'tick', asm,
                                    resolve=SYMBOLS.get) is None
