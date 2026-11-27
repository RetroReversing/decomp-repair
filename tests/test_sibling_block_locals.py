"""Locals declared in separate inner blocks, written as one function-level local."""
from decomprepair import sibling_block_locals as module

SOURCE = '''void f(s32 n)
{
    s32 i;

    if (n) {
        f32 dist, speed;

        dist = g(n);
        speed = g(dist);
        h(speed, dist);
    }
    {
        Rec *p = &table[n];

        p->a = 1;
    }
    {
        f32 len;

        len = g(n);
        h(len, len);
    }
    {
        Rec *p = &table[n + 1];

        p->a = 2;
    }
}
'''


def _children(family, source=SOURCE):
    return [text for found, text in module.variants(source, 'f') if found == family]


def test_one_name_declared_in_sibling_blocks_is_declared_once():
    out = _children(module.SHARED)
    assert len(out) == 1
    assert out[0].count('Rec *p') == 1 and '    s32 i;\n    Rec *p;\n' in out[0]
    assert '        p = &table[n];\n' in out[0] and '        p = &table[n + 1];\n' in out[0]


def test_two_names_of_one_type_in_sibling_blocks_become_one():
    out = _children(module.MERGE)
    merged = next(t for t in out if '    s32 i;\n    f32 dist;\n' in t)
    assert '        f32 speed;\n' in merged and 'len' not in merged
    assert 'dist = g(n);\n        h(dist, dist);' in merged


def test_nested_blocks_and_taken_addresses_are_left_alone():
    nested = 'void f(void)\n{\n    s32 i;\n    {\n        f32 a;\n\n        a = g();\n        {\n            f32 b;\n\n            b = a;\n            h(a, b);\n        }\n    }\n}\n'
    assert module.variants(nested, 'f') == []
    taken = SOURCE.replace('h(len, len);', 'h(&len, len);')
    assert not any('len' not in t for t in _children(module.MERGE, taken))


def test_an_initialiser_followed_by_a_declaration_is_not_turned_into_a_statement():
    source = SOURCE.replace('Rec *p = &table[n];\n', 'Rec *p = &table[n];\n        s32 k;\n')
    assert _children(module.SHARED, source) == []
