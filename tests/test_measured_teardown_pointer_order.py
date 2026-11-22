from decomprepair import measured_teardown_pointer_order as repair

HEADER = 'typedef signed char s8; typedef signed short s16; typedef signed int s32;'
SOURCE = '''typedef s32 M2C_UNK;
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern void *selection;
extern s8 phase;
extern M2C_UNK state;
extern M2C_UNK cb_one;
extern M2C_UNK cb_two;
s32 f(s32 first_arg, M2C_UNK second_arg) {
    prepare();
    reset(first_arg, second_arg);
    phase = 2;
    M2C_FIELD(selection, M2C_UNK **, 8) = &cb_one;
    M2C_FIELD(selection, M2C_UNK **, 12) = &cb_two;
    M2C_FIELD(M2C_FIELD(&state, void **, 32), s16 *, 4) = 0;
    teardown(M2C_FIELD(&state, void **, 32));
    finish();
    return 1;
}
'''
OPS = ['jal prepare', 'jal reset', 'lui $v1, %hi(selection)', 'lw $v1, %lo(selection)($v1)',
       'lui $a0, %hi(records)', 'lw $a0, %lo(records)($a0)', 'addiu $v0, $zero, 2',
       'lui $at, %hi(phase)', 'sb $v0, %lo(phase)($at)', 'lui $v0, %hi(cb_one)',
       'addiu $v0, $v0, %lo(cb_one)', 'sw $v0, 8($v1)', 'lui $v0, %hi(cb_two)',
       'addiu $v0, $v0, %lo(cb_two)', 'sw $v0, 12($v1)', 'jal teardown', 'sh $zero, 4($a0)',
       'jal finish', 'nop']
CAND = OPS[:4] + OPS[6:15] + OPS[4:6] + OPS[15:]
ROWS = [('o', a, b) for a, b in zip(OPS, CAND)]


def variants(source=SOURCE, header=HEADER, rows=ROWS, flags=('-mgp32',), addresses=None):
    addresses = addresses if addresses is not None else {'state': 0x1000, 'records': 0x1020}
    return repair.variants(source, 'f', header, rows, flags, addresses.get)


def test_recovers_the_measured_pointer_lifetimes():
    (_, candidate), = variants()
    assert 'if (selection)' in candidate
    assert candidate.count('__repair_list = (s16 *)((char *)M2C_FIELD(&state, void **, 32) + 4);') == 2
    assert candidate.count('M2C_FIELD(__repair_selection, M2C_UNK **, 8) = &cb_one;') == 2
    assert candidate.count('return 1;') == 2


def test_requires_target_and_rejects_ambiguous_source():
    assert not variants(addresses={'state': 0x1000, 'records': 0x1024})
    assert not variants(rows=ROWS[:-2])
    assert not variants(flags=('-mabi=64',))
    assert not variants(source=SOURCE.replace('finish();', 'finish(); extra();'))
    assert not variants(source=SOURCE.replace('extern void *selection;', 'extern volatile void *selection;'))
    assert not variants(header=HEADER + '\n#define selection hidden')
    assert not variants(header=HEADER.replace('signed short', 'volatile short'))
