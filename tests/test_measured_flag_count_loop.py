from decomprepair import measured_flag_count_loop as repair

HEADER = 'typedef signed int s32; typedef unsigned short u16; typedef signed char s8;'
SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern int owner;
extern int state;
s32 count_flags(s32 flags) {
    s32 hits;
    s32 index;
    void *cursor;
    index = 0;
    cursor = M2C_FIELD(&owner, void **, 32);
    hits = 0;
    if (M2C_FIELD(&state, s32 *, 16) > 0) {
        do {
            if (M2C_FIELD(cursor, s32 *, 0) != 0) {
                if (M2C_FIELD(cursor, u16 *, 6) != 0) {
                    if (!(flags & 1)) { index += 1; }
                    else { goto hit; }
                } else {
                    if (flags & 2) { hit: hits += 1; }
                    goto next;
                }
            } else { next: index += 1; }
            cursor += 12;
        } while (index < M2C_FIELD(&state, s32 *, 16));
    }
    return hits;
}
'''
ROWS = [('r', op, '') for op in [
    'lui $v0, %hi(count)', 'lw $v0, %lo(count)($v0)', 'blez $v0, 0x70',
    'lhu $v0, 6($v1)', 'addiu $v1, $v1, 12',
]]
ADDRESSES = {'state': 0x1000, 'count': 0x1010}


def variants(source=SOURCE, header=HEADER, rows=ROWS, addresses=ADDRESSES):
    return repair.variants(source, 'count_flags', header, rows, addresses.get)


def test_rebuilds_the_same_count_loop_with_resolved_bound():
    (_, candidate), = variants()
    assert 'extern s32 count;' in candidate
    assert 'if (count > __repair_zero)' in candidate
    assert 'if (flags & 1) goto hit;' in candidate
    assert 'while (index < count)' in candidate


def test_does_not_guess_a_symbol_or_rewrite_observable_work():
    assert not variants(addresses={'state': 0x1000, 'count': 0x1014})
    assert not variants(rows=ROWS[:-1])
    assert not variants(source=SOURCE.replace('index += 1;', 'side(); index += 1;', 1))
    assert not variants(header=HEADER + '\nextern float count;')
    assert not variants(header=HEADER + '\n#define hits external_hits')
    assert not variants(source=SOURCE.replace('s32 count_flags(s32 flags)', 's32 count_flags(\ns32 flags)'))
