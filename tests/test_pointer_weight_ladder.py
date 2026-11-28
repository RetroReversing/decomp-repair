from decomprepair.pointer_weight_ladder import variants

SOURCE = '''
void f(void *arg) {
    void *p;
    p = arg + 4;
    use(p);
}
'''


def test_weights_the_existing_assignment_without_changing_its_expression():
    children = variants(SOURCE, 'f')
    assert len(children) == 5
    assert children[2][1].count('do {') == 4
    assert 'p = arg + 4;' in children[2][1]


def test_excludes_volatile_or_indirect_stores():
    assert not variants(SOURCE.replace('void *p;', 'void *volatile p;'), 'f')
    assert not variants(SOURCE.replace('p = arg + 4;', '*p = arg + 4;'), 'f')
