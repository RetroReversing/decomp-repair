from decomprepair.measured_kmc_list_count import variants

SOURCE = '''void f(void **head) {
    void *node;
    node = *head;
    if (node != NULL) {
        do {
            node = M2C_FIELD(node, void **, 4);
        } while (node != NULL);
    }
}'''
ROWS = [('|', 'move $v0, $zero', 'nop'), ('|', 'addiu $v0, $v0, 1', 'nop')]


def test_restores_counter_and_return():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_linked_list_count'
    assert fixed.startswith('u32 f(')
    assert 'u32 __repair_count = 0;' in fixed
    assert '__repair_count++;' in fixed
    assert 'return __repair_count;' in fixed


def test_requires_target_and_simple_list_walk():
    assert not variants(SOURCE, 'f', '', ROWS[:1])
    assert not variants(SOURCE, 'f', 'void f(void **);', ROWS)
    assert not variants('void f(void **);\n' + SOURCE, 'f', '', ROWS)
    assert not variants(SOURCE.replace('node = M2C_FIELD', 'call(); node = M2C_FIELD'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('void *node;', 'volatile void *node;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('void *node;', 'void *node; int __repair_count;'), 'f', '', ROWS)
