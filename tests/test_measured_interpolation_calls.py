from decomprepair.measured_interpolation_calls import variants

SOURCE = '''
s16 lookup(s32);
s16 interpolate(s32 input) {
    s16 low;
    s32 index;
    index = input >> 4;
    low = lookup(index);
    return (s16) (low + (((input & 0xF) * (lookup(index + 1) - low)) / 15));
}
'''
ROWS = [
    (' ', 'jal lookup', 'jal lookup'),
    ('o', 'sll $s0, $v0, 0x10', ''),
    (' ', 'jal lookup', 'jal lookup'),
    ('o', '', 'move $s0, $v0'),
    ('r', 'sra $s0, $s0, 0x10', 'sll $v1, $s0, 0x10'),
]


def test_stage_signed_lookup_values():
    [(family, candidate)] = variants(SOURCE, 'interpolate', '', ROWS)
    assert family == 'measured_interpolation_calls'
    assert '__repair_interp_first = lookup(index);' in candidate
    assert '__repair_interp_delta = lookup(index + 1) - low;' in candidate
    assert 'low = __repair_interp_first;' in candidate


def test_requires_call_and_narrowing_evidence():
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('s16 low;', 'volatile s16 low;'), '', ROWS),
        (SOURCE.replace('low = lookup(index);', 'if (input) low = lookup(index);'), '', ROWS),
        (SOURCE.replace('s16 lookup(s32);', 's32 lookup(s32);'), '', ROWS),
        (SOURCE.replace('index = input >> 4;', 'index = input >> 4; use(&input);'), '', ROWS),
        (SOURCE, '#define lookup(x) helper(x)', ROWS),
        (SOURCE, 'typedef volatile int s32;', ROWS),
        (SOURCE + '\ns16 lookup(s32 x) { return x; }', '', ROWS),
    ]:
        assert variants(source, 'interpolate', header, rows) == []
