from decomprepair import measured_call_slot_setup as repair

HEADER = 'typedef signed int s32; typedef signed char s8; typedef unsigned char u8;'
SOURCE = '''typedef s32 M2C_UNK;
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
M2C_UNK submit(M2C_UNK, M2C_UNK, void *);
extern M2C_UNK state;
s32 f(void *owner, void *item) {
    s32 result;
    M2C_FIELD(&state, void **, 16) = owner;
    M2C_FIELD(&state, void **, 12) = item;
    M2C_FIELD(&state, s8 *, 20) = 1;
    M2C_FIELD(owner, s32 *, 8) = 1;
    result = 0;
    if (M2C_FIELD(item, u8 *, 20) != 0) {
        M2C_FIELD(&state, void **, 16) = owner;
        M2C_FIELD(&state, void **, 12) = item;
        M2C_FIELD(owner, s32 *, 8) = 1;
        submit(0, 1, (char *)&state + 12);
        result = 1;
    }
    return result;
}
'''
ROWS = [('r', op, '') for op in [
    'lui $a3, %hi(slot)', 'addiu $a3, $a3, %lo(slot)', 'addiu $a2, $zero, 1',
    'lui $at, %hi(owner_slot)', 'sw $a0, %lo(owner_slot)($at)', 'sw $a1, ($a3)',
    'lui $at, %hi(flag)', 'sb $v0, %lo(flag)($at)', 'sw $a2, 8($a0)',
    'lbu $v0, 20($a1)', 'beqz $v0, 80', 'move $a1, $zero',
    'sw $a2, 8($a0)', 'jal submit', 'nop',
]]
ADDRESSES = {'state': 0x1000, 'slot': 0x100c, 'owner_slot': 0x1010, 'flag': 0x1014}


def variants(source=SOURCE, header=HEADER, rows=ROWS, flags=('-mgp32',), addresses=ADDRESSES):
    return repair.variants(source, 'f', header, rows, flags, addresses.get)


def test_recovers_slot_and_forwarded_argument():
    (_, candidate), = variants()
    assert 'M2C_UNK submit();' in candidate
    assert '__repair_slot = (void **)((char *)&state + 12);' in candidate
    assert 'M2C_FIELD(owner, volatile s32 *, 8)' in candidate
    assert 'submit(owner, 0, 1, __repair_slot);' in candidate


def test_does_not_guess_addresses_call_contract_or_volatile_types():
    assert not variants(addresses={**ADDRESSES, 'slot': 0x1008})
    assert not variants(rows=ROWS[:-1])
    assert not variants(flags=('-mabi=64',))
    assert not variants(header=HEADER + '\nvoid submit(int);')
    assert not variants(source=SOURCE.replace('submit(0, 1,', 'submit(0, 2,'))
    assert not variants(source=SOURCE.replace('result = 0;', 'side_effect(); result = 0;'))
    assert not variants(header=HEADER.replace('signed int', 'volatile int'))
    assert not variants(rows=ROWS[:2] + [('r', 'lw $a0, 0($a0)', '')] + ROWS[2:])
