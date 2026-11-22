from decomprepair.measured_zero_record_pairs import variants

SOURCE = '''extern void *head;
extern int base;
typedef struct { void *field_0; void *field_4; int field_8; int field_C; int field_10; int field_14; } __repair_record_head;
void init(void) {
    M2C_FIELD(&base, s32 *, 0x20) = 0;
    M2C_FIELD(&base, s32 *, 0x24) = 0;
    ((__repair_record_head*)head)->field_10 = 0;
    ((__repair_record_head*)head)->field_14 = 0;
    ((__repair_record_head*)head)->field_8 = 0;
    ((__repair_record_head*)head)->field_C = 0;
}
'''
TARGET = ['lui $v0, %hi(head)', 'lw $v0, %lo(head)($v0)', 'move $a0, $zero', 'move $a1, $zero', 'lui $at, %hi(first)', 'sw $a0, %lo(first)($at)',
          'lui $at, %hi(second)', 'sw $a1, %lo(second)($at)', 'sw $a0, 0x10($v0)', 'sw $a1, 0x14($v0)',
          'sw $a0, 8($v0)', 'sw $a1, 0xc($v0)']
ROWS = [('r', x, x if i < 2 else 'nop') for i, x in enumerate(TARGET)]


def resolve(name):
    return {'base': 0x1000, 'first': 0x1020, 'second': 0x1024}.get(name)


def test_merges_verified_global_and_record_zero_pairs():
    result = variants(SOURCE, 'init', '', ROWS, resolve=resolve)
    assert len(result) == 1
    assert 'M2C_FIELD(&base, u64 *, 0x20) = 0;' in result[0][1]
    assert 'M2C_FIELD(head, u64 *, 0x10) = 0;' in result[0][1]
    assert 'M2C_FIELD(head, u64 *, 0x8) = 0;' in result[0][1]


def test_rejects_unverified_alias_layout_or_extra_qualifiers():
    assert not variants(SOURCE, 'init', '', ROWS)
    assert not variants(SOURCE, 'init', '', ROWS, resolve=lambda _: 0)
    assert not variants(SOURCE.replace('int field_C;', 'short field_C;'), 'init', '', ROWS, resolve=resolve)
    assert not variants(SOURCE.replace('extern void *head;', 'extern volatile void *head;'), 'init', '', ROWS,
                        resolve=resolve)
    assert not variants(SOURCE, 'init', '', [('r', x, x) for x in TARGET], resolve=resolve)
