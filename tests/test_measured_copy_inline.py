from decomprepair.local_inline_repairs import FAMILY, measured_record_copy_inline

SOURCE = """typedef struct { f32 x, y, z; } Vector;
void f(void *base, unsigned index) {
    void *address;
    f32 dest[3];
    address = base + index * 12;
    *((Vector *) dest) = *((Vector *) address);
    sink(dest);
}"""
ROWS = [
    ('r', 'lw $v1, ($v0)', 'lw $v0, ($v1)'),
    ('r', 'lw $a1, 4($v0)', 'lw $a1, 4($v1)'),
    ('r', 'lw $a2, 8($v0)', 'lw $a2, 8($v1)'),
    ('r', 'sw $v1, 0xb0($sp)', 'sw $v0, 0xb0($sp)'),
]


def test_inline_measured_single_use_record_address():
    expected = SOURCE.replace(
        '    address = base + index * 12;\n    *((Vector *) dest) = *((Vector *) address);',
        '    *((Vector *) dest) = *((Vector *) (void *)(base + index * 12));',
    )
    assert measured_record_copy_inline(SOURCE, 'f', ROWS) == [(FAMILY, expected)]
    assert not measured_record_copy_inline(SOURCE, 'f', ROWS[:-1])
    assert not measured_record_copy_inline(SOURCE.replace('sink(dest);', 'sink(address);'), 'f', ROWS)
    assert not measured_record_copy_inline(SOURCE.replace('    address =', '    if (index)\n        address ='), 'f', ROWS)
    assert not measured_record_copy_inline(SOURCE.replace('    address =', '    f32 *dest = other();\n    address ='), 'f', ROWS)
