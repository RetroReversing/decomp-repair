import re

from decomprepair.paired_statement_moves import FAMILIES, single_moves, variants

SOURCE = '''extern int a, b, c, d;
void f(void) {
    int i;
    a = 1;
    b = 2;
    c = 3;
    d = 4;
    i = 0;
}'''


def statements(source):
    return re.findall(r'^\s+((?:[a-z]) = \d);', source, re.M)


def test_proposes_only_candidates_two_moves_reach():
    proposed = variants(SOURCE, 'f', limit=200)
    assert proposed and {family for family, _ in proposed} == set(FAMILIES)
    candidates = [source for _, source in proposed]
    assert len(set(candidates)) == len(candidates)
    assert SOURCE not in candidates
    assert not set(candidates) & set(single_moves(SOURCE, 'f'))
    for source in candidates:
        assert sorted(statements(source)) == sorted(statements(SOURCE))  # a reordering, nothing added or lost


def test_dependent_statements_never_trade_places():
    source = '''extern int a, b, c;
void f(void) {
    a = 1;
    b = a;
    c = 2;
    a = 3;
}'''
    for _, candidate in variants(source, 'f', limit=500) + [(None, s) for s in single_moves(source, 'f')]:
        lines = statements(candidate)
        assert lines.index('a = 1') < lines.index('a = 3')
        assert candidate.index('b = a;') > candidate.index('a = 1;')
        assert candidate.index('b = a;') < candidate.index('a = 3;')


def test_a_call_keeps_its_place_among_statements_that_touch_memory():
    source = '''extern int a, b;
extern void g(int);
void f(void) {
    int i;
    a = 1;
    g(2);
    b = 3;
    i = 4;
    i = 5;
}'''
    for _, candidate in variants(source, 'f', limit=500):
        assert candidate.index('a = 1;') < candidate.index('g(2);') < candidate.index('b = 3;')


def test_a_pointer_write_does_not_cross_other_memory_access():
    source = '''extern int a, b;
extern char buf[];
void f(void) {
    a = 1;
    buf[2] = 5;
    b = 3;
    a = 4;
}'''
    for candidate in single_moves(source, 'f') + [s for _, s in variants(source, 'f', limit=500)]:
        assert candidate.index('a = 1;') < candidate.index('buf[2] = 5;') < candidate.index('b = 3;')


def test_blocks_loops_labels_and_gotos_are_barriers():
    source = '''extern int a, b, c, d;
void f(int n) {
    int i;
    a = 1;
    b = 2;
    if (n) { c = 3; d = 4; }
    c = 5;
    d = 6;
    while (n) { n = n - 1; a = 7; b = 8; }
    top:
    a = 9;
    b = 10;
    goto top;
}'''
    for _, candidate in variants(source, 'f', limit=300):
        assert candidate.index('b = 2;') < candidate.index('if (n)') < candidate.index('c = 5;')
        assert candidate.index('d = 6;') < candidate.index('while (n)')
        assert candidate.index('while (n)') < candidate.index('top:') < candidate.index('goto top;')
        assert max(candidate.index('a = 9;'), candidate.index('b = 10;')) < candidate.index('goto top;')
        assert candidate.index('top:') < min(candidate.index('a = 9;'), candidate.index('b = 10;'))


def test_every_block_is_its_own_run():
    source = '''extern int a, b, c, d;
void f(int n) {
    if (n) {
        a = 1;
        b = 2;
        c = 3;
        d = 4;
    }
}'''
    assert variants(source, 'f', limit=10)


def test_seeded_and_bounded():
    source = 'extern int ' + ', '.join(f'v{i}' for i in range(40)) + ';\nvoid f(void) {\n' + ''.join(
        f'    v{i} = {i};\n' for i in range(40)) + '}'
    first = variants(source, 'f', limit=30, seed=7)
    assert first == variants(source, 'f', limit=30, seed=7)
    assert first != variants(source, 'f', limit=30, seed=8)
    assert len(first) == 30
    skip = {candidate for _, candidate in first[:10]}
    assert not skip & {candidate for _, candidate in variants(source, 'f', limit=30, seed=7, exclude=skip)}


def test_locals_may_cross_calls_but_globals_may_not():
    source = '''extern int a;
extern void g(int);
void f(void) {
    int i, j;
    i = 1;
    g(2);
    j = 3;
    a = 4;
}'''
    seen = {candidate for _, candidate in variants(source, 'f', limit=200)} | set(single_moves(source, 'f'))
    assert any(candidate.index('i = 1;') > candidate.index('g(2);') for candidate in seen)
    assert all(candidate.index('g(2);') < candidate.index('a = 4;') for candidate in seen)


def test_a_statement_naming_a_macro_stays_put():
    """A macro's effects are unknown, so nothing crosses a statement that names one."""
    macro = variants(SOURCE, 'f', header='#define c 3\n', limit=200)
    assert macro
    for _, candidate in macro:
        assert candidate.index('b = 2;') < candidate.index('c = 3;') < candidate.index('d = 4;')
        assert candidate.index('a = 1;') < candidate.index('c = 3;')


def test_nothing_for_volatile_asm_missing_or_single_statement_functions():
    assert variants(SOURCE.replace('extern int', 'extern volatile int'), 'f') == []
    assert variants(SOURCE, 'missing') == []
    assert variants('void f(void) { __asm__("nop"); }', 'f') == []
    assert variants('void f(void) { a = 1; }', 'f') == []
