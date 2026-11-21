import pytest

from decomprepair.parallel_byte_cursors import variants

SOURCE = """
void scan(u8 *records, int n) {
    u8 *base;
    void *lead;
    int i;
    base = records;
    i = 0;
    lead = base + 2;
    do {
        consume(*base, *(u8 *)((char *)(lead) + -1), *(u8 *)((char *)(lead) + 0));
        lead += 3;
        i += 1;
        base += 3;
    } while (i < n);
}
"""


def test_parallel_cursor_rewrites_fixed_displacements():
    [(family, source)] = variants(SOURCE, 'scan')
    assert family == 'parallel_byte_cursor'
    assert source == SOURCE.replace('*(u8 *)((char *)(lead) + -1)', 'base[1]').replace(
        '*(u8 *)((char *)(lead) + 0)', 'base[2]',
    )


@pytest.mark.parametrize(('old', 'new'), [
    ('lead += 3;', 'lead += 4;'),
    ('lead += 3;', 'if (n) lead += 3;'),
    ('consume(', 'base++; consume('),
    ('consume(', 'take_address(&(base)); consume('),
    ('consume(', 'entry: consume('),
    ('consume(', 'case 1: consume('),
    ('while (i < n)', 'while (i < n && base++)'),
    ('+ -1)', '+ -3)'),
    ('i += 1;', 'take_pointer(lead); i += 1;'),
])
def test_parallel_cursor_requires_stable_relation(old, new):
    assert not variants(SOURCE.replace(old, new), 'scan')



def test_parallel_cursor_rejects_shadowed_base_pointer():
    source = SOURCE.replace('    lead =', '    { unsigned short *base = words;\n    lead =')
    source = source.replace('while (i < n);', 'while (i < n); }')
    assert not variants(source, 'scan')
