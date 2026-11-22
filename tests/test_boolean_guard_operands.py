from decomprepair.boolean_guard_operands import FAMILY, variants

SOURCE = """void f(void *value) {
    int flag;
    void *ptr;
    ptr = fetch();
    if ((flag = value != NULL, ready()) && (flag & (ptr != NULL))) {
        sink();
    }
}"""
ROWS = [
    ('|', 'sltu $v1, $zero, $s2', 'beqz $s2, 0x50'),
    ('|', 'and $v0, $v0, $v1', 'andi $v0, $a0, 1'),
]


def test_proven_comparison_flag_in_guard():
    assert variants(SOURCE, 'f', ROWS) == [
        (FAMILY, SOURCE.replace('flag & (ptr', 'flag && (ptr')),
    ]
    assert not variants(SOURCE, 'f', ROWS[:1])
    assert not variants(SOURCE.replace('value != NULL', '2'), 'f', ROWS)
    assert not variants(SOURCE.replace('void *ptr', 'void *volatile ptr'), 'f', ROWS)
    assert not variants(SOURCE.replace('sink();', 'sink(&flag);'), 'f', ROWS)
    assert not variants(SOURCE, 'f', ROWS, '#define NULL read_null()')
