from decomprepair.measured_narrow_use import variants

SOURCE = """static inline u8 select(u8 *table, s32 key) {
    u32 byte;
    u32 result;
    byte = (u8) key;
    result = table[byte];
    if (result == byte) return 1;
    return 0;
}

s32 f(u8 *table, s32 key, s32 range) {
    s32 r;
    r = sample() & 0xffff;
    r = r % range;
    return r + select(table, key);
}
"""

ROWS = [
    ('i', 'andi $a0, $s1, 0xff', 'andi $v0, $v0, 0xffff'),
    ('i', 'andi $v0, $v0, 0xffff', 'andi $a0, $s1, 0xff'),
    ('r', 'andi $v1, $a0, 0xff', 'andi $a2, $v1, 0xff'),
    ('<', 'andi $v0, $a0, 0xff', ''),
]


def test_preserves_the_word_until_each_measured_narrow_use():
    [(family, helper), (_, remainder)] = variants(SOURCE, 'f', ROWS)
    assert family == 'measured_narrow_use'
    assert 'byte = key;' in helper
    assert 'table[(u8)byte]' in helper and 'result == (u8)byte' in helper
    assert 'r = sample();\n    r = (u16)r % range;' in remainder


def test_preserves_unrelated_and_escaping_values():
    modified = SOURCE.replace('result = table[byte];', 'use(byte); result = table[byte];')
    assert len(variants(modified, 'f', ROWS)) == 1
    modified = SOURCE.replace('r = sample()', 'set_ptr(&(r)); r = sample()')
    assert len(variants(modified, 'f', ROWS)) == 1
    assert not variants(SOURCE, 'f', [])


def test_shared_halfword_index_restages_the_two_score_loops():
    from decomprepair.measured_narrow_use import shared_halfword_index_variants

    source = """void f(void) {
    s32 i, best, score, index, player;
    s16 *winner;
    union { s16 *scores; void *other; } table;
    do {
        u16 slot = lookup((u16)i);
        score = table.scores[slot];
        if (best < score) { best = score; player = slot; }
        i++;
    } while (i < count);
    do {
        index = (u16)lookup((u16)i);
        score = table.scores[index];
        i++;
        best += *winner == score;
    } while (i < count);
}
"""
    rows = []
    for carrier in ('$a0', '$v0'):
        rows += [
            (' ', 'jal lookup', 'jal lookup'),
            (' ', 'andi $a0, $s0, 0xffff', 'andi $a0, $s0, 0xffff'),
            ('r', 'andi $v1, $v0, 0xffff', f'andi {carrier}, $v0, 0xffff'),
            ('r', 'sll $v0, $v1, 1', f'sll $v0, {carrier}, 1'),
            (' ', 'addu $v0, $v0, $s2', 'addu $v0, $v0, $s2'),
            ('r', 'lh $a0, ($v0)', 'lh $v1, ($v0)'),
        ]
    [(family, candidate)] = shared_halfword_index_variants(source, 'f', rows)
    assert family == 'shared_halfword_index'
    assert 's32 i, best, index, player; s32 score;' in candidate
    assert candidate.count('index = (u16)') == 2
    assert 'best += table.scores[index] == *winner;' in candidate
    assert not shared_halfword_index_variants(source, 'f', rows[:6])
    assert not shared_halfword_index_variants(source.replace('s16 *winner', 'volatile s16 *winner'), 'f', rows)
    assert not shared_halfword_index_variants(source.replace('    do {\n        index', '    use(index);\n    do {\n        index'),
                                             'f', rows)


def test_byte_backedge_uses_the_loop_entry_carrier():
    from decomprepair.measured_narrow_use import byte_backedge_variants

    source = """void f(u8 *start) {
    u8 *ptr = start;
    long raw;
    s32 phase;
    u32 opcode;
    raw = *ptr;
    if (((u8)raw) != 12) {
        opcode = raw & 255;
        do {
            switch (opcode) {
            case 1: raw *= 2; ptr += raw; break;
            default: ptr++; break;
            }
            phase = *ptr;
            opcode = phase & 255;
        } while (phase != 12);
    }
}
"""
    rows = [
        ('r', 'lbu $a0, ($t0)', 'lbu $v0, ($t0)'),
        ('r', 'bne $a0, $t1, 0x38', 'bne $v0, $t1, 0x38'),
        ('r', 'andi $v1, $a0, 0xff', 'andi $v1, $v0, 0xff'),
    ]
    [(family, text)] = byte_backedge_variants(source, 'f', rows)
    assert family == 'byte_backedge_carrier'
    assert 'raw = *ptr;\n            opcode = raw & 255;' in text
    assert 'while (raw != 12)' in text
    assert not byte_backedge_variants(source, 'f', rows[:-1])
    assert not byte_backedge_variants(source.replace('    }\n}', '    }\n    use(raw);\n}'), 'f', rows)
    assert not byte_backedge_variants(source.replace('u8 *ptr', 'volatile u8 *ptr'), 'f', rows)


def test_explicit_byte_boolean_carrier_preserves_masked_reads():
    from decomprepair.measured_narrow_use import boolean_byte_carriers

    source = """void f(void) {
    s32 flag;
    s32 value;
    flag = 0;
    if (ready) {
        value = state != 7;
        flag = (u8)value;
    }
    if (flag & 0xff) work();
}
"""
    rows = [
        (' ', 'sltu $v0, $zero, $v0', 'sltu $v0, $zero, $v0'),
        ('|', 'move $s0, $v0', 'andi $s0, $v0, 0xff'),
    ]
    assert boolean_byte_carriers(source, 'f', rows) == [
        ('boolean_byte_carrier', source.replace('s32 flag;', 'u8 flag;').replace('(u8)value', 'value'))
    ]
    assert not boolean_byte_carriers(source, 'f', rows[1:])
    assert not boolean_byte_carriers(source.replace('if (flag & 0xff) work();', 'work(&flag);'), 'f', rows)
    assert not boolean_byte_carriers(source.replace('flag = 0;', 'flag = 256;'), 'f', rows)
