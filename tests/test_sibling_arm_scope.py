import re

from decomprepair import sibling_arm_scope
from decomprepair.sibling_arm_scope import HELD, SPLIT, variants

SOURCE = """extern s8 T[];
extern s8 count;
extern s8 wanted;
extern u8 mode;

u8 check(void) {
    s32 flag = 0;
    s8 *p;

    if (count != 0) {
        if (mode == 0) {
            p = &T[0];
            if (p[0] != wanted) {
                flag = 1;
            } else if (p[1] != count - 1) {
                flag = 1;
            }
        } else if (mode == 1) {
            p = &T[0];
            if (p[0] != wanted) {
                flag = 1;
            } else if (p[1] != count) {
                flag = 1;
            }
        }
    }
    return flag;
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_split_and_weighted_in_one_child():
    children = [_flat(c) for f, c in variants(SOURCE, 'check') if f == SPLIT]
    assert any('p_1 = &T[0];' in c and 'do { if (p_1[0] != wanted)' in c and 'p_2 = &T[0];' in c for c in children)


def test_held_count_with_the_else_tail_weighted():
    children = [_flat(c) for f, c in variants(SOURCE, 'check') if f == HELD]
    wanted = 'else do { if (p_1[1] != held_count - 1) { flag = 1; } } while (0);'
    child = next(c for c in children if wanted in c)
    assert 'int held_count = count;' in child
    assert 'if (held_count != 0)' in child
    # the later arm keeps its own load
    assert 'p_2[1] != count)' in child


def test_a_global_the_guarded_code_writes_is_not_held():
    written = SOURCE.replace('flag = 1;\n            }\n        } else if (mode == 1)',
                             'count = 0;\n            }\n        } else if (mode == 1)')
    assert not any(f == HELD for f, _ in variants(written, 'check'))
    called = SOURCE.replace('p = &T[0];', 'p = &T[0];\n            refresh();', 1)
    assert not any(f == HELD for f, _ in variants(called, 'check'))


def test_declines_without_a_repeated_address():
    assert variants(SOURCE.replace('p = &T[0];', 'p = &T[1];', 1), 'check') == []
    assert variants('int f(int a) { return a; }', 'f') == []


def test_declared():
    assert sibling_arm_scope.REPAIR['families'] == (SPLIT, HELD)
