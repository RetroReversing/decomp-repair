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


def test_sink_repeated_null_flag_to_last_test():
    source = """void f(void) {
    int flag;
    void *ptr;
    void *other;
    ptr = fetch();
    other = fetch();
    if (((flag = ptr != NULL, ready()) || (flag = ptr != NULL, available())) && (flag && other != NULL)) {
        sink();
    }
}"""
    rows = [
        ('r', 'sltu $v0, $zero, $s4', 'sltu $a0, $zero, $s4'),
        ('|', 'sltu $v0, $zero, $s4', 'nop'),
        ('r', 'sltu $v1, $zero, $s2', 'sltu $v0, $zero, $s2'),
        ('r', 'and $v0, $v0, $v1', 'and $v0, $a0, $v0'),
    ]
    expected = source.replace('flag = ptr != NULL, ', '').replace('flag && other', 'ptr != NULL && other')
    assert variants(source, 'f', rows) == [(FAMILY, expected)]
    assert not variants(source, 'f', rows[1:])
    assert not variants(source.replace('other = fetch();', 'other = fetch(); escape(&ptr);'), 'f', rows)
    assert not variants(source.replace('ready()', '(ptr = fetch(), ready())'), 'f', rows)
    assert not variants(source, 'f', rows, '#define ready() \\\n mutate(ptr)')
