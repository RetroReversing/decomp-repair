"""Byte stores to word-declared symbols in a loop: bases and the stored constant held in locals."""
from decomprepair import word_symbol_loop_bases as m

SOURCE = '''extern M2C_UNK D_A;
extern M2C_UNK D_B;

void f(void) {
    s32 idx;
    s32 i;
    s32 j;
    s32 *tail;

    i = 0;
    do {
        j = 0;
loop_2:
        idx = i + j;
        *(s8 *)(idx + &D_A) = 1;
        tail = (s32 *)(idx + &D_B);
        j += 1;
        *tail = 0;
        if (j <= 0) {
            goto loop_2;
        }
        i += 1;
    } while (i < 4);
}
'''


def children():
    return dict(m.variants(SOURCE, 'f'))


def test_bases_constant_and_narrowed_pointer_as_one_child():
    out = children()['word_symbol_loop_bases']
    assert '    i = 0;\n    base1 = (s32)&D_A;\n    val = 1;\n    base2 = (s32)&D_B;\n    do {' in out
    assert '*(s8 *)(idx + base1) = val;' in out and 'tail = (s8 *)(idx + base2);' in out
    assert '    s8 *tail;\n' in out and 's32 base1;' in out and 's32 base2;' in out and 's8 val;' in out
    assert '(&D_A)' not in out and '&D_B)' not in out


def test_the_plain_child_keeps_the_literal():
    out = children()['word_symbol_loop_bases_plain']
    assert '*(s8 *)(idx + base1) = 1;' in out and 'val' not in out


def test_leaves_sums_outside_loops_arrays_and_taken_names():
    assert not m.variants(SOURCE.replace('do {', '{').replace('} while (i < 4);', '}'), 'f')
    assert '(s32)&D_A' not in dict(m.variants(SOURCE.replace('extern M2C_UNK D_A;', 'extern s8 D_A;'), 'f'))['word_symbol_loop_bases_plain']
    assert not m.variants(SOURCE.replace('idx = i', 'base1 = i'), 'f')
    assert not m.variants('void f(void) {\n    s32 i;\n    do {\n        i += 1;\n    } while (i < 4);\n}\n', 'f')
