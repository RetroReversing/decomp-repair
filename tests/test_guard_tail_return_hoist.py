"""guard_tail_return_hoist: the closing `if (C) { BODY } return V;` as an early return, and the join copy unified."""
from decomprepair import guard_tail_return_hoist as g
from decomprepair import registry

DRAFT = '''void *make(s32);
void *get();
s32 pick(s32, s32);

void *func_1(s32 arg0) {
    s32 temp_s0;
    void *var_s0;
    void *var_v0;

    var_v0 = get();
    if (var_v0 == NULL) {
        if (pick(0, 100) >= 51) {
            temp_s0 = pick(0, 65535);
            var_s0 = make(temp_s0);
        } else {
            var_s0 = make(arg0);
            M2C_FIELD(var_s0, s32 *, 0x18) = 0x4000;
        }
        M2C_FIELD(var_s0, s32 *, 0x78) = pick(0, 9);
        var_v0 = var_s0;
    }
    return var_v0;
}
'''
UNIFIED = '''void *func_1(s32 arg0) {
    s32 temp_s0;
    void *var_s0;

    var_s0 = get();
    if (var_s0 == NULL) {
        if (pick(0, 100) >= 51) {
            temp_s0 = pick(0, 65535);
            var_s0 = make(temp_s0);
        } else {
            var_s0 = make(arg0);
            M2C_FIELD(var_s0, s32 *, 0x18) = 0x4000;
        }
        M2C_FIELD(var_s0, s32 *, 0x78) = pick(0, 9);
    }
    return var_s0;
}
'''


def by_family(source, name='func_1'):
    return dict(g.variants(source, name))


def test_the_unified_function_gets_the_early_return():
    child = by_family(UNIFIED)[g.HOIST]
    assert 'if (var_s0 != NULL) {\n        return var_s0;\n    }\n' in child
    assert 'if (pick(0, 100) >= 51) {\n        temp_s0' in child  # the block's statements, one level out
    assert child.rstrip().endswith('return var_s0;\n}')
    assert child.count('return var_s0;') == 2 and g.UNIFY not in by_family(UNIFIED)


def test_the_draft_gets_the_unify_and_the_pair_as_one_child():
    kids = by_family(DRAFT)
    assert set(kids) == {g.UNIFY, g.HOIST, g.BOTH}
    assert 'var_s0' not in kids[g.UNIFY] and 'void *var_v0;' in kids[g.UNIFY]
    assert kids[g.UNIFY].count('var_v0 = ') == 3
    assert 'void *var_v0;' in kids[g.BOTH]
    both = kids[g.BOTH].split('func_1(s32 arg0)')[1]
    assert 'var_s0' not in both and 'if (var_v0 != NULL) {\n        return var_v0;' in both
    assert 'var_v0 = var_s0' in kids[g.HOIST] and g.HOIST in kids


def test_the_condition_forms():
    for cond, want in (('!p', 'if (p) {'), ('p == 0', 'if (p != 0) {'), ('p != NULL', 'if (p == NULL) {'), ('a < b', 'if (a >= b) {')):
        src = f'void *f(void *p, s32 a, s32 b) {{\n    if ({cond}) {{\n        p = g(p);\n    }}\n    return p;\n}}\n'
        assert want + '\n        return p;' in by_family(src, 'f')[g.HOIST]
    mixed = 'void *f(void *p, s32 a) {\n    if (p == NULL && a) {\n        p = g(a);\n    }\n    return p;\n}\n'
    assert 'if (!(p == NULL && a)) {' in by_family(mixed, 'f')[g.HOIST]
    number = 'int f(int a) {\n    if (a == 3) {\n        h();\n    }\n    return 0;\n}\n'
    assert 'if (a != 3) {\n        return 0;\n    }\n    h();' in by_family(number, 'f')[g.HOIST].replace('        h', '    h')


def test_refusals():
    cases = {
        'else': 'int f(int a) {\n    if (a) {\n        h();\n    } else {\n        k();\n    }\n    return a;\n}\n',
        'declaration': 'int f(int a) {\n    if (a == 0) {\n        int t;\n        t = h();\n        a = t;\n    }\n    return a;\n}\n',
        'label': 'int f(int a) {\n    if (a == 0) {\nagain:\n        a = h();\n        goto again;\n    }\n    return a;\n}\n',
        'empty': 'int f(int a) {\n    if (a == 0) {\n    }\n    return a;\n}\n',
        'work after': 'int f(int a) {\n    if (a == 0) {\n        h();\n    }\n    k();\n    return a;\n}\n',
        'else if': 'int f(int a) {\n    if (a == 1) {\n        k();\n    } else if (a == 0) {\n        h();\n    }\n    return a;\n}\n',
        'expression': 'int f(int a) {\n    if (a == 0) {\n        h();\n    }\n    return a + 1;\n}\n',
        'no tail': 'int f(int a) {\n    if (a == 0) {\n        return h();\n    }\n    return a;\n}\n',
    }
    for label, src in cases.items():
        kids = by_family(src, 'f')
        if label == 'no tail':
            assert g.HOIST in kids  # a return inside the block is still the same program on both paths
        else:
            assert g.HOIST not in kids, label


def test_the_unify_refuses_what_it_would_change():
    base = UNIFIED.replace('    var_s0 = get();', '    var_v0 = get();').replace('    if (var_s0 == NULL) {', '    if (var_v0 == NULL) {') \
        .replace('    return var_s0;', '    return var_v0;').replace('    void *var_s0;\n', '    void *var_s0;\n    void *var_v0;\n') \
        .replace('pick(0, 9);\n    }', 'pick(0, 9);\n        var_v0 = var_s0;\n    }')
    assert g.UNIFY in by_family(base)
    refused = {
        'v read in the block': base.replace('M2C_FIELD(var_s0, s32 *, 0x78)', 'M2C_FIELD(var_v0, s32 *, 0x78)'),
        's used after the block': base.replace('    return var_v0;', '    pick(0, var_s0 != 0);\n    return var_v0;'),
        'other type': base.replace('void *var_v0;', 'long var_v0;'),
        'address taken': base.replace('var_s0 = make(arg0);', 'var_s0 = make(&var_s0);'),
        's read first': base.replace('        if (pick(0, 100) >= 51) {', '        pick(0, var_s0);\n        if (pick(0, 100) >= 51) {', 1),
        'copy of another value': base.replace('var_v0 = var_s0;', 'var_v0 = temp_s0;'),
    }
    for label, src in refused.items():
        assert g.UNIFY not in by_family(src), label


def test_the_children_are_bounded_and_the_source_unchanged_when_nothing_applies():
    assert len(g.variants(DRAFT, 'func_1')) <= 3
    plain = 'int f(int a) {\n    return a;\n}\n'
    assert g.variants(plain, 'f') == [] and g.variants(plain, 'missing') == []


def test_it_declares_itself():
    found = {r.module: r for r in registry.declared()}
    assert set(found['guard_tail_return_hoist'].families) == set(g.FAMILIES)
    assert registry.problems(found['guard_tail_return_hoist']) == []
