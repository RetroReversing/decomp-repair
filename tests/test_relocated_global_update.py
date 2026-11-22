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


def test_reload_wrapper_rebinds_only_the_word_read_by_both_calls():
    from decomprepair.relocated_global_update import rewrite_reload_wrapper

    annotated = [
        ('27BDFFE8', 'addiu $sp, $sp, -24'),
        ('AFB00010', 'sw $s0, 16($sp)'),
        ('00808021', 'move $s0, $a0'),
        ('3C048001', 'lui $a0, %hi(state + 256)'),
        ('8C840100', 'lw $a0, %lo(state + 256)($a0)'),
        ('AFBF0014', 'sw $ra, 20($sp)'),
        ('0C000000', 'jal set_value'),
        ('24050001', 'addiu $a1, $zero, 1'),
        ('3C058001', 'lui $a1, %hi(state + 256)'),
        ('8CA50100', 'lw $a1, %lo(state + 256)($a1)'),
        ('0C000000', 'jal use_value'),
        ('02002021', 'move $a0, $s0'),
        ('8FBF0014', 'lw $ra, 20($sp)'),
        ('8FB00010', 'lw $s0, 16($sp)'),
        ('03E00008', 'jr $ra'),
        ('27BD0018', 'addiu $sp, $sp, 24'),
    ]
    asm = '\n'.join(f'/* {4*i:06X} {0x80001000+4*i:08X} {word} */ {line}'
                    for i, (word, line) in enumerate(annotated))
    source = '''
extern M2C_UNK state;
void f(s32 input) {
    set_value(M2C_FIELD(&state, s32 *, 256), 1);
    use_value(input, M2C_FIELD(&state, s32 *, 256));
}
'''
    resolve = {'state': 0x80010000, 'D_80010100': 0x80010100}.get
    fixed = rewrite_reload_wrapper(source, 'f', asm, resolve=resolve)
    assert fixed
    assert 'extern s32 D_80010100;' in fixed
    assert 'set_value(D_80010100, 1);\n    use_value(input, D_80010100);' in fixed
    assert rewrite_reload_wrapper(source, 'f', asm.replace('8CA50100', '8CA50104'), resolve=resolve) is None
    assert rewrite_reload_wrapper(source.replace('), 1);', '), 2);'), 'f', asm, resolve=resolve) is None
    assert rewrite_reload_wrapper(source, 'f', asm, 'extern u32 D_80010100;', resolve) is None


_BRANCH_BYTE_ASM = '''
/* 00 80000100 3C038000 */ lui $v1, %hi(state + 0x30)
/* 04 80000104 90632030 */ lbu $v1, %lo(state + 0x30)($v1)
/* 08 80000108 24020001 */ addiu $v0, $zero, 1
/* 0C 8000010C 14620003 */ bne $v1, $v0, .Ldone
/* 10 80000110 00000000 */ nop
/* 14 80000114 3C018000 */ lui $at, %hi(state + 0x30)
/* 18 80000118 A0202030 */ sb $zero, %lo(state + 0x30)($at)
'''
_BRANCH_BYTE_SOURCE = '''
extern M2C_UNK state;
void clear_pending(void) {
    if (M2C_FIELD(&state, u8 *, 0x30) == 1) {
        M2C_FIELD(&state, u8 *, 0x30) = 0U;
        notify();
    }
}
'''


def test_branch_byte_uses_one_name_with_two_independent_relocations():
    from decomprepair.relocated_global_update import branch_byte_applies, rewrite_branch_byte

    resolve = {'state': 0x80002000, 'D_80002030': 0x80002030}.get
    assert branch_byte_applies(_BRANCH_BYTE_ASM)
    fixed = rewrite_branch_byte(_BRANCH_BYTE_SOURCE, 'clear_pending', _BRANCH_BYTE_ASM, resolve=resolve)
    assert 'extern u8 D_80002030;' in fixed
    assert 'if (D_80002030 == 1)' in fixed
    assert 'D_80002030 = 0U;' in fixed
    assert 'notify();' in fixed


def test_branch_byte_rejects_a_different_machine_store_address_and_volatile_header():
    from decomprepair.relocated_global_update import rewrite_branch_byte

    resolve = {'state': 0x80002000, 'D_80002030': 0x80002030}.get
    asm = _BRANCH_BYTE_ASM.replace('A0202030', 'A0202031')
    assert not rewrite_branch_byte(_BRANCH_BYTE_SOURCE, 'clear_pending', asm, resolve=resolve)
    assert not rewrite_branch_byte(_BRANCH_BYTE_SOURCE, 'clear_pending', _BRANCH_BYTE_ASM,
                                   'extern volatile char state[];', resolve)


INCREMENT = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern M2C_UNK arena;
void update(void *p) {
    use(p);
    M2C_FIELD(&arena, s32 *, 0x40) = (s32) (M2C_FIELD(&arena, s32 *, 0x40) + 1);
}
'''
INCREMENT_ASM = '''
/* 00 80001000 0C000000 */ jal use
/* 04 80001004 00000000 */ nop
/* 08 80001008 3C028003 */ lui $v0, %hi(arena + 0x40)
/* 0C 8000100C 8C429120 */ lw $v0, %lo(arena + 0x40)($v0)
/* 10 80001010 24420001 */ addiu $v0, $v0, 1
/* 14 80001014 3C018003 */ lui $at, %hi(arena + 0x40)
/* 18 80001018 AC229120 */ sw $v0, %lo(arena + 0x40)($at)
/* 1C 8000101C 03E00008 */ jr $ra
/* 20 80001020 00000000 */ nop
'''


def test_recover_direct_word_increment_at_verified_relocations():
    candidate = repair.rewrite_increment(INCREMENT, 'update', INCREMENT_ASM, resolve=SYMBOLS.get)
    assert candidate == INCREMENT.replace('void update', 'extern s32 D_80029120;\n\nvoid update').replace(
        'M2C_FIELD(&arena, s32 *, 0x40)', 'D_80029120')


@pytest.mark.parametrize('source,asm,symbols', [
    (INCREMENT, INCREMENT_ASM.replace('8C429120', '8C429124'), SYMBOLS),
    (INCREMENT, INCREMENT_ASM.replace('AC229120', 'AC229124'), SYMBOLS),
    (INCREMENT.replace('+ 1);', '+ 2);'), INCREMENT_ASM, SYMBOLS),
    (INCREMENT.replace('(type_ptr)((s8 *)(expr) + (offset))', '(type_ptr)(side_effect())'), INCREMENT_ASM, SYMBOLS),
    (INCREMENT, INCREMENT_ASM, {'arena': 0x800290E0}),
])
def test_increment_rejects_unproven_addresses_and_macros(source, asm, symbols):
    assert repair.rewrite_increment(source, 'update', asm, resolve=symbols.get) is None
