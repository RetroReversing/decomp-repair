from decomprepair.measured_slot_flip_copy import variants

SOURCE = '''typedef int s32;
extern s32 base;
void flip(void) {
    char *addr;
    s32 off;
    void *ptr;
    ptr = (char *)&base + 0x20;
    M2C_FIELD(&base, s32 *, 0x20) = (s32) (1 - M2C_FIELD(&base, s32 *, 0x20));
    off = M2C_FIELD(&base, s32 *, 0x20) * 4;
    addr = (char *)(off + (ptr - 8));
    *(s32 *)(addr) = M2C_FIELD((ptr + off), s32 *, -0x10);
}
'''
T = ['lui $a0, %hi(slot)', 'addiu $a0, $a0, %lo(slot)', 'lw $v1, ($a0)', 'addiu $v0, $zero, 1',
     'subu $v0, $v0, $v1', 'sw $v0, ($a0)', 'lui $v0, %hi(slot)', 'lw $v0, %lo(slot)($v0)',
     'sll $v0, $v0, 2', 'addu $v1, $a0, $v0', 'lw $v1, -0x10($v1)', 'addiu $a0, $a0, -8',
     'addu $v0, $v0, $a0']
ROWS = [('r', x, 'nop') for x in T]


def resolve(name):
    return {'base': 0x1000, 'slot': 0x1020}.get(name)


def test_recovers_direct_slot_alias_and_copy_order():
    result = variants(SOURCE, 'flip', '', ROWS, resolve=resolve)
    assert len(result) == 1
    assert 'extern s32 slot;' in result[0][1]
    assert 'off = slot * 4;' in result[0][1]
    assert 'ptr -= 8;' in result[0][1]


def test_requires_alias_and_exact_unshared_source_shape():
    assert not variants(SOURCE, 'flip', '', ROWS)
    assert not variants(SOURCE, 'flip', '', ROWS, resolve=lambda _: 0)
    assert not variants(SOURCE, 'flip', 'extern s32 slot;', ROWS, resolve=resolve)
    assert not variants(SOURCE.replace('ptr = (char *)&base', 'use(ptr); ptr = (char *)&base'), 'flip', '', ROWS,
                        resolve=resolve)
    assert not variants(SOURCE, 'flip', '', [('r', x, x) for x in T], resolve=resolve)
