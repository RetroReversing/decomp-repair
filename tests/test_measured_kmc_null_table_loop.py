from decomprepair.measured_kmc_null_table_loop import variants

SOURCE = '''
void release(void *p) {
    s32 index;
    s32 table;
    s32 value;
    index = 0;
    do {
        table = M2C_FIELD(p, s32 *, 0x38);
        if (table == 0) {
            index += 1;
        } else {
            value = M2C_FIELD(((index * 4) + table), s32 *, 0x30);
            index += 1;
            if (value != 0) { free_item(value); }
        }
    } while (index < 12);
}'''
ROWS = [('|', 'beql $v1, $zero, 0x40', 'bnez $v1, 0x2c'),
        ('>', '', 'j release+0x44')]


def test_recover_for_loop_from_duplicated_increments():
    result = variants(SOURCE,'release','',ROWS)
    assert len(result)==1
    assert 'for (index = 0; index < 12; index++)' in result[0][1]
    assert 'index += 1' not in result[0][1]
    assert 'free_item(value)' in result[0][1]


def test_requires_safe_counter_and_evidence():
    assert not variants(SOURCE,'release','',[])
    assert not variants(SOURCE.replace('index < 12','index < 0'),'release','',ROWS)
    assert not variants(SOURCE.replace('s32 index;', 'volatile s32 index;'),'release','',ROWS)
    assert not variants(SOURCE.replace('index = 0;', 'save(&index); index = 0;'),'release','',ROWS)
    assert not variants(SOURCE,'release','#define free_item(x) consume(index, x)',ROWS)
    assert not variants(SOURCE,'release','#define index shared',ROWS)


def test_rejects_nested_function_that_can_access_counter():
    nested = SOURCE.replace('    index = 0;', '    void free_item(s32 x) { index = x; }\n    index = 0;')
    assert not variants(nested,'release','',ROWS)
