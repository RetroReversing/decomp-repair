"""Compiler witnesses for using the probe's float local for the reload."""

from decomprepair.clamp_return_local import FAMILY, variants

HEADER = 'f32 absolute(f32);\n'
FUNCTION = """void match_demo(void* p, int flags, int mask, f32 input) {
    f32 sample;
    f32 bound;
    if ((flags & mask) && (absolute(input) < 0.01f)) {
        *((f32*)(((char*)p)+0x18)) = 0.0f;
    }
    sample = *((f32*)(((char*)p)+0x18));
    bound = -0.25f;
}
"""
INLINE = """
static inline f32* field(void* base) {
    return (f32*)(((char*)base)+0x18);
}
"""
ROWS = [
    (' ', 'jal absolute', 'jal absolute'),
    (' ', 'neg.s $f12, $f0', 'neg.s $f12, $f0'),
    (' ', 'c.lt.s $f0, $f2', 'c.lt.s $f0, $f2'),
    (' ', 'bc1tl .Lnext', 'bc1tl .Lnext'),
    (' ', 'sw $zero, 0x18($s0)', 'sw $zero, 0x18($s0)'),
    ('<', 'lwc1 $f0, 0x18($s0)', ''),
    (' ', 'lui $at, 0xbe80', 'lui $at, 0xbe80'),
    (' ', 'ori $at, $at, 0x0', 'ori $at, $at, 0x0'),
    ('i', 'mtc1 $at, $f2', 'mtc1 $at, $f0'),
    ('|', 'nop', 'lwc1 $f2, 0x18($s0)'),
    ('i', 'c.lt.s $f0, $f2', 'c.lt.s $f2, $f0'),
]


def test_float_probe_reuses_plain_or_inline_field_local():
    changed = FUNCTION.replace('absolute(input)', '(sample = absolute(input))')
    assert variants(FUNCTION, 'match_demo', ROWS, header=HEADER) == [(FAMILY, changed)]
    inline = INLINE + FUNCTION.replace('*((f32*)(((char*)p)+0x18))', '*field(p)')
    assert variants(inline, 'match_demo', ROWS, header=HEADER) == [
        (FAMILY, inline.replace('absolute(input)', '(sample = absolute(input))'))
    ]


def test_two_verified_sites_are_tried_together_then_individually():
    body = FUNCTION[FUNCTION.index('    if'):FUNCTION.rindex('}')]
    source = FUNCTION[:FUNCTION.rindex('}')] + body + '}'
    candidates = variants(source, 'match_demo', ROWS + ROWS, header=HEADER)
    assert [changed.count('(sample = absolute(input))') for _, changed in candidates] == [2, 1, 1]


def test_wrong_receiver_wrong_bound_or_missing_register_witness_skips():
    for source in (
        FUNCTION.replace('0x18', '0x28'),
        FUNCTION.replace('-0.25f', '-0.5f'),
        FUNCTION.replace('    sample = *((f32*)(((char*)p)+0x18));',
                         '    sample = *((f32*)(((char*)other)+0x18));'),
    ):
        assert variants(source, 'match_demo', ROWS, header=HEADER) == []
    assert variants(FUNCTION, 'match_demo', ROWS[:-1], header=HEADER) == []


def test_address_taken_or_macro_local_skips():
    escaped = FUNCTION.replace('    bound =', '    use(&sample);\n    bound =')
    assert variants(escaped, 'match_demo', ROWS, header=HEADER) == []
    assert variants(FUNCTION, 'match_demo', ROWS, header=HEADER + '#define sample current\n') == []
