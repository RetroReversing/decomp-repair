from decomprepair import held_mask_constant as repair
from decomprepair import registry

SOURCE = '''typedef unsigned short u16;
int absolute(int);
void steer(int *p, int d) {
    int step;
    int other;

    if (d > 0) {
        step = 4 & 0xFFFF;
        if (step < absolute(d)) {
            p[0] = p[1] + step;
        }
    } else {
        other = 4 & 0xFFFF;
        if (other < absolute(d)) {
            p[0] = p[1] - other;
        }
    }
}
'''

ASM = 'addiu $s3, $zero, 4\nandi $a0, $s3, 0xFFFF\n'


def test_temporaries_become_one_held_halfword():
    family, child = repair.variants(SOURCE, 'steer', asm=ASM)[0]
    assert family == 'held_mask_constant'
    assert '{\n    u16 held_4 = 4;\n' in child
    assert '0xFFFF' not in child and 'step' not in child and 'other' not in child
    assert child.count('held_4') == 5
    assert 'p[0] = p[1] + held_4;' in child and 'if (held_4 < absolute(d))' in child


def test_second_child_keeps_the_temporaries():
    child = repair.variants(SOURCE, 'steer')[1][1]
    assert 'step = held_4;' in child and 'other = held_4;' in child


def test_a_reassigned_temporary_is_kept():
    source = SOURCE.replace('p[0] = p[1] + step;', 'step += 1;\n            p[0] = p[1] + step;')
    child = repair.variants(source, 'steer')[0][1]
    assert 'step = held_4;' in child and 'other' not in child


def test_byte_mask_without_the_typedef():
    source = 'int f(int x) {\n    return g(x, 7 & 0xFF);\n}\n'
    assert repair.variants(source, 'f')[0][1] == (
        'int f(int x) {\n    unsigned char held_7 = 7;\n    return g(x, held_7);\n}\n')


def test_only_whole_operands_and_a_target_mask():
    assert repair.variants('int f(int x) {\n    return x & 4 & 0xFFFF;\n}\n', 'f') == []
    assert repair.variants('int f(int x) {\n    x = 0 & 0xFFFF;\n    return x;\n}\n', 'f') == []
    assert repair.variants(SOURCE, 'steer', asm='addiu $s3, $zero, 4\n') == []


def test_declared_in_the_registry():
    assert any('held_mask_constant' in entry.families for entry in registry.declared())
