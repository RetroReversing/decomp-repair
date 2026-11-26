import re

from decomprepair import else_arm_symbol_pointer
from decomprepair.else_arm_symbol_pointer import FAMILY, variants

SOURCE = """extern s8 T[];
extern s8 row;
extern s8 column;
extern u8 mode;

s32 check(void) {
    s32 flag = 0;
    if (row < 23) {
        if (T[0] == row && (T[1] == column + 1 || T[1] == column - 1)) {
            if (mode == 1) flag = 1;
        } else if (T[0] == row + 1 && T[1] == column) {
            if (mode == 3) flag = 1;
        } else if (T[0] != row - 1 || T[1] != column)
            flag = 1;
        else if (mode == 2)
            flag = 1;
    }
    return flag & 0xFF;
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_pointer_split_and_chain_scope_in_one_child():
    children = [_flat(c) for f, c in variants(SOURCE, 'check') if f == FAMILY]
    first = children[0]
    assert 's8 *p_T;' in first
    assert 'do { if (T[0] == row && (T[1] == column + 1 || T[1] == column - 1))' in first
    assert 'else { do { p_T = T; } while (0); if (p_T[0] == row + 1 && p_T[1] == column)' in first
    assert 'if (p_T[0] != row - 1) flag = 1; else if (p_T[1] != column) flag = 1;' in first
    assert 'else if (mode == 2) flag = 1; } } while (0);' in first


def test_pointer_alone_is_offered_too():
    children = [_flat(c) for _, c in variants(SOURCE, 'check')]
    assert any('p_T = T;' in c and '|| p_T[1] != column' in c and 'do { if (T[0]' not in c for c in children)


def test_needs_two_elements_after_the_else():
    source = SOURCE.replace('T[1]', 'T[0]')
    assert variants(source, 'check') == []


def test_declared():
    assert else_arm_symbol_pointer.REPAIR['families'] == (FAMILY,)
