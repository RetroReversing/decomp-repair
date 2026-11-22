from decomprepair import target_memory_schedule_repairs as repairs

SOURCE = '''
extern int table;
int read(int index, int scale) {
    return *(int *)((char *)&table + 16 + (index * 4)) + (scale * 20);
}
'''


def variants(source=SOURCE, header=''):
    return repairs.variants(source, 'read', header, [(repairs.indexed_load_before_arithmetic, True)])


def test_stages_indexed_load_with_unrelated_volatile_header():
    result = variants(header='extern volatile int unrelated;')
    assert len(result) == 1
    assert 'int repair_indexed_word = *(int *)' in result[0][1]
    assert 'return repair_indexed_word + (scale * 20);' in result[0][1]


def test_rejects_volatile_and_macro_operands_and_side_effects():
    assert not variants(header='extern volatile int table;')
    assert not variants(header='#define index next()')
    assert not variants(header='typedef volatile int int;')
    assert not variants(SOURCE.replace('scale * 20', 'next() * 20'))
    assert not variants(SOURCE.replace('index * 4', 'index++ * 4'))
    assert not variants(SOURCE.replace('extern int table;', 'extern volatile int table;'))
