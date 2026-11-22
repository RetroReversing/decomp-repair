from decomprepair import measured_child_slot_update as repair

HEADER = '''typedef signed char s8; typedef unsigned char u8; typedef signed short s16;
typedef unsigned short u16; typedef signed int s32;'''
SOURCE = '''typedef s32 M2C_UNK;
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern M2C_UNK state;
extern s32 slots;
void f(void *node) {
    u16 enabled; u8 index; void *child;
    if (M2C_FIELD(M2C_FIELD(&state, void **, 32), u16 *, 30) == 0) {
        enabled = M2C_FIELD(M2C_FIELD(&state, void **, 32), u16 *, 26);
        if (enabled == 1) {
            index = M2C_FIELD(M2C_FIELD(node, s32 **, 72), u8 *, 3);
            if ((index < 5U) && (M2C_FIELD((slots + (index * 68)), u16 *, 8) & 512)) {
                child = M2C_FIELD(node, void **, 4);
                apply(child, 16);
                M2C_FIELD(M2C_FIELD(child, void **, 92), s32 *, 108) = (s32) enabled;
                M2C_FIELD(M2C_FIELD(child, void **, 48), s32 *, 108) = (s32) enabled;
                M2C_FIELD((slots + (*M2C_FIELD(node, s32 **, 72) * 68)), s16 *, 12) = 0;
                M2C_FIELD((slots + (*M2C_FIELD(node, s32 **, 72) * 68)), s16 *, 10) = 4;
            }
        }
    }
}
'''
ROWS = [('r', op, '') for op in [
    'lui $v1, %hi(record)', 'lw $v1, %lo(record)($v1)',
    'lhu $v0, 30($v1)', 'lhu $s2, 26($v1)', 'lbu $a0, 3($v0)',
    'sltiu $v0, $a0, 5', 'lui $v0, %hi(slots)', 'lw $v0, %lo(slots)($v0)',
    'lhu $v0, 8($v0)', 'andi $v0, $v0, 512', 'move $s0, $s1', 'lw $s1, 4($s1)',
    'addiu $a1, $zero, 16', 'jal apply', 'move $a0, $s1',
    'lw $v0, 92($s1)', 'sw $s2, 108($v0)', 'lw $v0, 48($s1)', 'sw $s2, 108($v0)',
    'lui $a0, %hi(slots)', 'lw $a0, %lo(slots)($a0)', 'sh $zero, 12($v0)',
    'sll $v0, $v1, 4', 'addu $v0, $v0, $v1', 'sll $v0, $v0, 2',
    'addu $a0, $a0, $v0', 'addiu $v0, $zero, 4', 'sh $v0, 10($a0)',
]]


def variants(source=SOURCE, header=HEADER, rows=ROWS, flags=('-mgp32',), addresses=None):
    addresses = addresses if addresses is not None else {'state': 0x1000, 'record': 0x1020}
    return repair.variants(source, 'f', header, rows, flags, addresses.get)


def test_captures_parent_and_stages_indexed_addresses():
    (_, candidate), = variants()
    assert '__repair_original = node;' in candidate
    assert 'node = M2C_FIELD(node, void **, 4);' in candidate
    assert 'apply(node, 16);' in candidate
    assert '__repair_slot += (*M2C_FIELD(__repair_original, s32 **, 72) * 68);' in candidate


def test_requires_the_measured_shape_addresses_and_abi():
    assert not variants(addresses={'state': 0x1000, 'record': 0x1024})
    assert not variants(rows=ROWS[:-1])
    assert not variants(flags=('-mabi=64',))
    assert not variants(header=HEADER + '\n#define node other')
    assert not variants(source=SOURCE.replace('apply(child, 16);', 'apply(child, 16); other();'))
    assert not variants(header=HEADER.replace('signed int', 'volatile int'))
