import re

from decomprepair import switch_table_density as density

ASM = '''
    addiu $v1, $v0, -0x1
    sltiu $v0, $v1, 0x65
    beqz $v0, .L80000100
    sll $v0, $v1, 2
    addu $v0, $v0, $s2
    lw $v0, 0x0($v0)
    jr $v0
'''
SOURCE = '''void f(int k) {
    switch (k) {
    case 1: a(); break;
    case 3: b(); break;
    case 4: c(); break;
    case 40: d(); break;
    case 90: e(); break;
    }
}
'''


def labels(text):
    return [int(v, 0) for v in re.findall(r'\bcase\s+(\w+)\s*:', text)]


def test_table_is_read_from_the_check_and_the_jump():
    assert density.tables(ASM) == [(1, 101)]
    assert density.tables('sltiu $v0, $v1, 0x65\nbeqz $v0, .L1\njr $ra\n') == []


def test_a_sparse_switch_is_filled_until_gcc_would_use_a_table():
    (family, text), = density.variants(SOURCE, 'f', ASM)
    assert family == 'switch_table_density'
    added = set(labels(text)) - set(labels(SOURCE))
    assert {2, 101} <= added
    assert min(labels(text)) == 1 and max(labels(text)) == 101
    values, _ = density.arms(text[text.index('switch'):])
    assert 100 <= 10 * density.count(values)


def test_added_labels_share_an_existing_default():
    source = SOURCE.replace('case 90: e(); break;', 'case 90: e(); break;\n    default: other(); break;')
    (_, text), = density.variants(source, 'f', ASM)
    assert re.search(r'case 101:\s*default:\s*other\(\);', text)


def test_a_run_longer_than_two_counts_twice():
    assert density.count({1: 1, 2: 1, 3: 1, 4: 1, 5: 2}) == 3


def test_a_dense_switch_or_another_table_is_left_alone():
    dense = 'void f(int k) { switch (k) { case 1: a(); break; case 2: b(); break; case 3: c(); break; case 4: d(); break; case 5: e(); break; } }'
    assert density.variants(dense, 'f', ASM.replace('0x65', '0x5')) == []
    assert density.variants(SOURCE, 'f', ASM.replace('0x65', '0x20')) == []
