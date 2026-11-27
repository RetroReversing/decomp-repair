"""The store after an `if`/`else` tree written at the end of every branch that reaches it."""
from decomprepair.join_store_into_leaves import FAMILY, variants

# A game initialiser (SN64 GCC 2.8.1, N64): the level reset after a nested two-way setup.
TREE = '''void f(u8 fresh)
{
    if (fresh) {
        if (easy() == 0) {
            lives = 3;
        } else {
            lives = 2;
        }
    } else {
        total = saved;
    }
    level = 0;
    if (a != 0 || b != 0) {
        level = pick;
    }
}
'''

WANT = '''void f(u8 fresh)
{
    if (fresh) {
        if (easy() == 0) {
            lives = 3;
            do { level = 0; } while (0);
        } else {
            lives = 2;
            do { level = 0; } while (0);
        }
    } else {
        total = saved;
        do { level = 0; } while (0);
    }
    if (a != 0 || b != 0) {
        level = pick;
    }
}
'''


def test_every_branch_gets_the_store_wrapped_first():
    out = variants(TREE, 'f')
    assert out[0] == (FAMILY, WANT)
    assert out[1] == (FAMILY, WANT.replace('do { level = 0; } while (0);', 'level = 0;'))


def test_a_nested_tree_also_offers_the_outer_branches():
    outer = variants(TREE, 'f')[2][1]
    assert outer.count('level = 0;') == 2
    assert '            lives = 2;\n        }\n        do { level = 0; } while (0);\n    } else {' in outer


def test_a_branch_that_leaves_gets_no_copy():
    source = '''void f(s32 x)
{
    if (x) {
        return;
    } else {
        y = 1;
    }
    z = 2;
}
'''
    out = variants(source, 'f')
    assert [child.count('z = 2;') for _, child in out] == [1, 1]
    assert 'return;\n    } else {\n        y = 1;\n        do { z = 2; } while (0);' in out[0][1]


def test_refused_shapes():
    tree = 'void f(s32 x)\n{\n    if (x) {\n        A\n    } else {\n        y = 1;\n    }\n    B\n}\n'
    for arm, after in (('y = 2;', 'g();'),                     # a call, not a store
                       ('y = 2;', 'z = g();'),
                       ('s32 y = 0;', 'z = y;'),               # a branch's own local would capture the name
                       ('y = 2;', 's32 z = 0;')):
        assert variants(tree.replace('A', arm).replace('B', after), 'f') == [], (arm, after)
    assert variants('void f(s32 x)\n{\n    if (x) {\n        y = 1;\n    }\n    z = 2;\n}\n', 'f') == []  # no else
