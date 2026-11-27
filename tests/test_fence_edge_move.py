"""A statement moved across one edge of a one-shot fence."""
from decomprepair.fence_edge_move import FAMILY_IN, FAMILY_OUT, variants

SAVED = '''void f(char *p)
{
    int x;
    *((int *) (p + 0x34)) = 0;
 do { *((short *) (p + 0x10)) = 0x1000; *((short *) (p + 0xE)) = 0x1000; *((short *) (p + 0xC)) = 0x1000; } while (0);
    *(p + 0x74) = 2;
}
'''


def _flat(source):
    return ' '.join(source.split())


def _children(source, family):
    return [_flat(src) for fam, src in variants(source, 'f') if fam == family]


FIRST = '*((short *) (p + 0x10)) = 0x1000;'
SECOND = '*((short *) (p + 0xE)) = 0x1000;'
THIRD = '*((short *) (p + 0xC)) = 0x1000;'


def test_the_last_statement_leaves_the_fence_and_comes_first():
    child = _children(SAVED, FAMILY_OUT)[0]
    assert f'do {{ {FIRST} {SECOND} }} while (0); {THIRD} *(p + 0x74) = 2;' in child


def test_the_first_statement_and_two_statements_can_leave_too():
    children = _children(SAVED, FAMILY_OUT)
    assert any(f'{FIRST} do {{ {SECOND} {THIRD} }} while (0);' in c for c in children)
    assert any(f'do {{ {FIRST} }} while (0); {SECOND} {THIRD}' in c for c in children)


def test_a_neighbour_joins_the_fence_at_either_end():
    children = _children(SAVED, FAMILY_IN)
    assert any(f'{THIRD} *(p + 0x74) = 2; }} while (0);' in c for c in children)
    assert any(f'do {{ *((int *) (p + 0x34)) = 0; {FIRST}' in c for c in children)


def test_declarations_breaks_and_if_heads_stay_put():
    declared = 'void f(void)\n{\n    do { int a = 1; g(a); } while (0);\n}\n'
    assert all('do { g(a); } while (0)' not in c for c in _children(declared, FAMILY_OUT))
    broken = 'void f(int c)\n{\n    do { if (c) { break; } g(1); g(2); } while (0);\n}\n'
    assert variants(broken, 'f') == []
    headed = 'void f(int c)\n{\n    if (c) g(0);\n    do { g(1); } while (0);\n}\n'
    assert variants(headed, 'f') == []
