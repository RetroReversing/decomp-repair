"""tail_exit_guard_first: the closing failure tail as the guard in front of the work."""
from decomprepair import registry
from decomprepair import tail_exit_guard_first as t

SOURCE = '''int *load(int *list, unsigned index, int *loaded) {
    if (index >= limit) {
        return list;
    }
    if (index < slots) {
        *list++ = 1;
        *loaded = 1;
        return list;
    }
    *loaded = 0;
    return list;
}
'''
GUARDED = '''int *load(int *list, unsigned index, int *loaded) {
    if (index >= limit) {
        return list;
    }
    if (index >= slots) {
        *loaded = 0;
        return list;
    }
    *list++ = 1;
    *loaded = 1;
    return list;
}
'''


def children(source, name='load'):
    return [child for _family, child in t.variants(source, name)]


def test_the_failure_tail_becomes_the_guard():
    assert children(SOURCE) == [GUARDED]


def test_work_with_declarations_keeps_its_block():
    source = SOURCE.replace('        *list++ = 1;\n', '        int tag = index;\n        *list++ = tag;\n')
    child, = children(source)
    assert '    {\n        int tag = index;\n' in child
    assert 'if (index >= slots) {\n        *loaded = 0;\n        return list;\n    }\n' in child


def test_void_returns():
    source = '''void set(int x) {
    if (x) {
        work(x);
        return;
    }
    count = 0;
    return;
}
'''
    child, = children(source, 'set')
    assert 'if (!x) {\n        count = 0;\n        return;\n    }\n    work(x);\n    return;\n}' in child


def test_refused_shapes():
    bare = SOURCE.replace('    *loaded = 0;\n', '')            # guard_shape's own shape
    falls = SOURCE.replace('        return list;\n    }\n    *loaded = 0;', '    }\n    *loaded = 0;')
    jumps = SOURCE.replace('        *list++ = 1;\n', '        goto out;\n    out:\n')
    other = SOURCE.replace('    }\n    *loaded = 0;', '    } else {\n        *loaded = 2;\n    }\n    *loaded = 0;')
    for source in (bare, falls, jumps, other):
        assert children(source) == []


def test_registered():
    assert t.FAMILY in {family for repair in registry.declared() for family in repair.families}
