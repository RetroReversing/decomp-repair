from decomprepair.masked_lookup_switch import candidate

SOURCE = """void *lookup(s32 resource, s32 scratch) {
    s32 category;
    s32 index;
    s32 table;
    u32 slot;
    s32 *entry;
    table = scratch;
    index = resource & 0xFFF;
    category = resource & 0xF000;
    if (category != 0x6000) {
        if (category == 0) {
            slot = index & 0xFFFF;
            if ((slot < 32U) && (first != 0)) {
                entry = (slot * 4) + first;
                goto read_entry;
            }
            goto missing;
        }
        if (category == 0x4000) {
            slot = index & 0xFFFF;
            if (slot < 4U) {
                return (slot * 12) + &buffer;
            }
            goto missing;
        }
        if (category == 0x7000) {
            slot = index & 0xFFFF;
            if (slot < 8U) {
                table = extra;
                goto read_table;
            }
            goto missing;
        }
        goto missing;
    }
    slot = index & 0xFFFF;
    if (slot < 8U) {
        table = last;
read_table:
        if (table != 0) {
            entry = (slot * 4) + table;
read_entry:
            return base + *entry;
        }
        goto missing;
    }
missing:
    return lookup(3, table);
}
"""
ROWS = [
    (' ', 'addiu $sp, $sp, -0x18', 'addiu $sp, $sp, -0x18'),
    ('r', 'andi $v1, $a0, 0xfff', 'andi $a2, $a0, 0xfff'),
    (' ', 'andi $a0, $a0, 0xf000', 'andi $a0, $a0, 0xf000'),
    *[(' ', 'nop', 'nop')] * 117,
]


def test_masked_lookup_switch_recovers_cases_and_fallback():
    fixed = candidate(SOURCE, 'lookup', '', ROWS)
    assert 'switch (resource & 0xf000)' in fixed
    assert '((s32 *)first)[index]' in fixed
    assert '(index * 12) + (u32)&buffer' in fixed
    assert '((s32 *)last)[index]' in fixed
    assert '((s32 *)extra)[index]' in fixed
    assert 'return lookup(3);' in fixed


def test_masked_lookup_switch_rejects_unknown_effects_and_changed_jumps():
    assert candidate(SOURCE.replace('goto read_entry;', 'goto read_table;'), 'lookup', '', ROWS) is None
    assert candidate(SOURCE.replace('table = last;', 'touch(); table = last;'), 'lookup', '', ROWS) is None
    assert candidate(SOURCE, 'lookup', 'void *lookup(s32, s32);', ROWS) is None
