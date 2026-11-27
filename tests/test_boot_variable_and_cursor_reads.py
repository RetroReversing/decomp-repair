from decomprepair import (
    boot_variable_literal,
    consecutive_postincrement,
    constant_bound_local,
    shared_decrement_in_place,
)

SOURCE = '''extern u32 osMemSize;
extern u32 T[];
extern Row R[];

void run(void)
{
    u32 *e;
    u32 start;
    u32 n;

    n = osMemSize;
    if (n > 0x3FFFFF) {
        T[2] = n - 1 + 0x80000000;
        T[6] = n - 1 + 0xA0000000;
    }
    e = T;
    while (*e < 0x80000000) {
        e += 2;
    }
    n = 0;
    start = 0x80000000;
    do {
        R[n].start = start;
        R[n].end = e[0];
        R[n].attr = e[1];
        e += 2;
        start = R[n].end + 1;
        n++;
    } while (start != 0);
}
'''


def only(module, source=SOURCE):
    children = module.variants(source, 'run')
    assert len(children) == 1 and children[0][0] == module.FAMILY
    return children[0][1]


def test_boot_variable_read_becomes_the_fixed_address():
    assert 'n = (*(u32 *) 0x80000318);' in only(boot_variable_literal)
    cast = SOURCE.replace('n = osMemSize;', 'n = (*(s32 *)&osMemSize);')
    assert 'n = (*(s32 *) 0x80000318);' in only(boot_variable_literal, cast)
    written = SOURCE.replace('n = osMemSize;', 'n = osMemSize;\n    osMemSize = 0;')
    assert boot_variable_literal.variants(written, 'run') == []


def test_loop_bound_takes_the_local_set_after_the_loop():
    text = only(constant_bound_local)
    assert 'start = 0x80000000;\n    while (*e < start) {' in text
    assert text.count('start = 0x80000000;') == 1
    signed = SOURCE.replace('u32 start;', 's32 start;')
    assert constant_bound_local.variants(signed, 'run') == []


def test_indexed_reads_and_a_step_become_post_increments():
    text = only(consecutive_postincrement)
    assert 'R[n].end = *e++;\n        R[n].attr = *e++;' in text
    assert 'e += 2;\n        start' not in text
    gap = SOURCE.replace('e[1];', 'e[2];')
    assert consecutive_postincrement.variants(gap, 'run') == []


def test_a_shared_decrement_is_applied_once():
    text = only(shared_decrement_in_place)
    assert 'n--;\n        T[2] = n + 0x80000000;\n        T[6] = n + 0xA0000000;' in text
    read_later = SOURCE.replace('    n = 0;\n', '    T[0] = n;\n    n = 0;\n')
    assert shared_decrement_in_place.variants(read_later, 'run') == []
