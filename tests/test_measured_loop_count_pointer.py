from decomprepair import measured_loop_count_pointer as repair

HEADER = '''typedef signed char s8; typedef unsigned short u16; typedef signed int s32;
typedef unsigned int u32;'''
SOURCE = '''typedef s32 M2C_UNK;
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern M2C_UNK state;
void f(void) {
    s32 index;
    void *node;
    index = 0;
    node = start();
    if (M2C_FIELD(M2C_FIELD(&state, void **, 32), u16 *, 14) != 0) {
        do {
            consume(node);
            /*__repair_loop_weight*/__repair_rows: {do {do {
            index += 1;} while (0);} while (0);}
if (0) goto __repair_rows;
            node = M2C_FIELD(node, void **, 0);
        } while ((u32) (index & 0xFF) < (u16) M2C_FIELD(M2C_FIELD(&state, void **, 32), u16 *, 14));
    }
}
'''
ROWS = [('o', target, candidate) for target, candidate in zip(
    ['lui $v0, %hi(records)', 'lw $v0, %lo(records)($v0)', 'addiu $s1, $s1, 1',
     'lhu $v1, 14($v0)', 'lw $s2, ($s2)', 'andi $v0, $s1, 255', 'sltu $v0, $v0, $v1'],
    ['addiu $s1, $s1, 1', 'lw $s2, ($s2)', 'lui $v0, %hi(records)',
     'lw $v0, %lo(records)($v0)', 'lhu $v1, 14($v0)', 'andi $v0, $s1, 255', 'sltu $v0, $v0, $v1'])]


def variants(source=SOURCE, header=HEADER, rows=ROWS, flags=('-mgp32',), addresses=None):
    addresses = addresses if addresses is not None else {'state': 0x1000, 'records': 0x1020}
    return repair.variants(source, 'f', header, rows, flags, addresses.get)


def test_recovers_pointer_name_and_both_count_spellings():
    options = variants()
    assert len(options) == 2
    all_counts, guard_only = (candidate for _, candidate in options)
    assert 'extern void *records;' in all_counts
    assert 'static inline u16 *__repair_count_ptr(void *p)' in all_counts
    assert all_counts.count('(*__repair_count_ptr(records))') == 2
    assert guard_only.count('(*__repair_count_ptr(records))') == 1
    assert '__repair_loop_weight' not in all_counts
    assert 'node = M2C_FIELD(node, void **, 0);' in all_counts


def test_requires_same_symbol_address_latch_and_inert_macros():
    assert not variants(addresses={'state': 0x1000, 'records': 0x1024})
    assert not variants(rows=ROWS[:-1])
    assert not variants(flags=('-mabi=64',))
    assert not variants(header=HEADER + '\n#define index something')
    assert not variants(header=HEADER.replace('signed int s32', 'volatile int s32'))
    assert not variants(source=SOURCE.replace('if (0) goto __repair_rows;', 'if (1) goto __repair_rows;'))
    assert not variants(source=SOURCE.replace('consume(node);', '/* keep this */ consume(node);'))
