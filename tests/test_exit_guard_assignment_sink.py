import re

import pytest

from decomprepair.exit_guard_assignment_sink import FAMILY, variants

SOURCE = """extern unsigned int gCount;
extern char gRows[];

unsigned char pick(unsigned int index) {
    char *base;

    base = gRows;
    if (index >= (unsigned int) gCount) {
        return 0U;
    }
    return *(unsigned char *)((index * 24) + base + 12);
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_moves_the_assignment_below_the_guard():
    [(family, child)] = variants(SOURCE, 'pick')
    assert family == FAMILY
    assert 'return 0U; } base = gRows; return *' in _flat(child)


def test_a_run_moves_together_and_crosses_a_row_of_guards():
    source = """int f(int a, int b) {
    int x;
    int y;
    x = a + 1;
    y = b;
    if (a == 0) {
        return 1;
    }
    if (b == 0) return 2;
    return x + y;
}
"""
    children = [_flat(child) for _, child in variants(source, 'f')]
    assert any('return 2; x = a + 1; y = b; return x + y;' in child for child in children)
    assert any('return 1; } x = a + 1; y = b; if (b == 0)' in child for child in children)
    assert any('x = a + 1; if (a == 0)' in child and 'return 2; y = b;' in child for child in children)


@pytest.mark.parametrize('edit', [
    ('if (index >= (unsigned int) gCount)', 'if (index >= limit())'),  # the call may change what is read
    ('if (index >= (unsigned int) gCount)', 'if (base != 0)'),  # the condition reads it
    ('return 0U;', 'return *base;'),  # the early path reads it
    ('return 0U;', 'index = 0;'),  # the guard falls through
    ('    char *base;\n', ''),  # a global: the early path must still store it
    ('    char *base;\n', '    static char *base;\n'),
    ('    base = gRows;\n', '    base = gRows;\n    keep(&base);\n'),
    ('    base = gRows;\n', '    base = next();\n'),
    ('return 0U;\n    }', 'return 0U;\n    } else {\n        index++;\n    }'),
])
def test_declines_when_the_move_could_change_behaviour(edit):
    assert variants(SOURCE.replace(*edit), 'pick') == []
