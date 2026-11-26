from decomprepair import guard_over_for as repair

SOURCE = '''extern u8 *table;
extern s8 first;
extern s8 second;
extern s8 rows[];

u8 find(void) {
    u8 i;
    s32 key1;
    s32 key2;
    s32 off;

    i = 0;
    if (table[2] != 0) {
        key1 = first;
        key2 = second;
        for (; i < table[2]; i++) {
            off = i * 5;
            if (key1 == rows[off] && key2 == rows[off]) {
                break;
            }
        }
    }
    return i;
}
'''


def test_the_guard_and_the_named_reads_become_one_for():
    body = SOURCE.replace('off = i * 5;\n', '').replace('rows[off]', 'rows[i * 5]').replace('    s32 off;\n', '')
    [(family, out)] = repair.variants(body, 'find')
    assert family == 'guard_over_for'
    assert 'for (i = 0; i < table[2]; i++) {' in out and 'if (table' not in out
    assert 'key1' not in out and 'if (first == rows[i * 5] && second == rows[i * 5]) {' in out
    assert out.endswith('    return i;\n}\n')


def test_a_body_that_writes_a_local_is_still_rewritten_and_one_that_stores_or_calls_is_not():
    assert repair.variants(SOURCE, 'find')  # `off = i * 5;` writes a local only
    assert not repair.variants(SOURCE.replace('off = i * 5;', 'off = i * 5;\n            rows[off] = 0;'), 'find')
    plain = SOURCE.replace('off = i * 5;\n', '')
    assert repair.variants(plain, 'find')
    assert not repair.variants(plain.replace('break;', 'stop();'), 'find')
    assert not repair.variants(plain.replace('extern u8 *table;', 'extern s8 *table;'), 'find')
    assert not repair.variants(plain.replace('return i;', 'return key1;'), 'find')


def test_the_module_declares_itself_to_the_registry():
    from decomprepair import registry
    declared = {r.module: r for r in registry.declared()}
    assert 'guard_over_for' in declared and not registry.problems(declared['guard_over_for'])
