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
    assert proposed and {family for family, _ in proposed} == {FAMILIES[0]}
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


def test_adjacent_declarations_are_all_locals():
    """Consecutive declarations used to consume each other's leading ';', hiding every second local."""
    source = '''extern int a;
extern void g(int);
void f(void) {
    char c1;
    char c2;
    register unsigned short c3;
    c1 = 1;
    c2 = 2;
    c3 = 3;
    g(1);
}'''
    from decomprepair.paired_statement_moves import wrapped_call_splits
    moved = [candidate for _, candidate in wrapped_call_splits(source, 'f', limit=100)]
    assert any(c.index('c1 = 1;') > c.index('do { g(1); } while (0);') for c in moved)
    assert any(c.index('c3 = 3;') > c.index('do { g(1); } while (0);') for c in moved)


WRAPPED = '''extern int a, b;
extern void g(int);
void f(void) {
    char c1, c2;
    c1 = 1;
    c2 = 2;
    a = 5;
    g(1);
    b = c1;
    g(2);
}'''


def test_wrapped_call_splits_wrap_one_call_and_move_held_constants_past_it():
    from decomprepair.paired_statement_moves import wrapped_call_splits
    proposed = wrapped_call_splits(WRAPPED, 'f', limit=200)
    assert proposed and {family for family, _ in proposed} == {'wrapped_call_split'}
    candidates = [candidate for _, candidate in proposed]
    assert len(set(candidates)) == len(candidates) and WRAPPED not in candidates
    assert any('do { g(1); } while (0);' in c and c.index('c2 = 2;') > c.index('do { g(1); }') > c.index('c1 = 1;')
               for c in candidates)  # one constant before the wrapped call, one after it
    assert any('do { g(2); } while (0);' in c for c in candidates)
    assert all(c.count('do {') == 1 for c in candidates)


def test_wrapped_call_splits_never_move_a_constant_past_a_use_of_it():
    from decomprepair.paired_statement_moves import wrapped_call_splits
    for _, candidate in wrapped_call_splits(WRAPPED, 'f', limit=500):
        assert candidate.index('c1 = 1;') < candidate.index('b = c1;')


def test_wrapped_call_splits_only_wrap_plain_calls_and_move_only_literal_locals():
    from decomprepair.paired_statement_moves import wrapped_call_splits
    source = '''extern int a, b;
extern void g(int);
void f(int n) {
    int i;
    i = n;
    a = 1;
    g(2);
}'''
    for _, candidate in wrapped_call_splits(source, 'f', limit=100):
        assert candidate.index('i = n;') < candidate.index('g(2)')  # not a literal: stays put
        assert candidate.index('a = 1;') < candidate.index('g(2)')  # a global: stays put
    assert wrapped_call_splits('void f(void) { while (1) { } }', 'f') == []


def test_a_hex_literal_is_not_a_name():
    """0x64 once yielded the identifier 'x64', so a local held constant looked like a global and never crossed a call."""
    from decomprepair.paired_statement_moves import wrapped_call_splits
    source = '''extern void g(int);
void f(void) {
    char c64;
    char c2;
    c64 = 0x64;
    c2 = 0x2;
    g(1);
    g(2);
}'''
    assert any(c.index('c64 = 0x64;') > c.index('do { g(1); } while (0);') for _, c in wrapped_call_splits(source, 'f', limit=200))


MATRIX = '''void f(float *m, float s, float c) {
    m[0] = c;
    m[1] = s * c;
    m[2] = -s;
    m[3] = 0.0f;
}'''


def test_stores_to_different_constant_cells_of_one_array_swap():
    moved = [source for source in single_moves(MATRIX, 'f')]
    assert any(source.index('m[2]') < source.index('m[1]') for source in moved)
    assert any(source.index('m[3]') < source.index('m[0]') for source in moved)


def test_stores_that_could_overlap_stay_ordered():
    same_cell = MATRIX.replace('m[1] = s * c', 'm[0] = s * c')
    assert all(source.index('m[0] = c') < source.index('m[0] = s') for source in single_moves(same_cell, 'f'))
    reads_memory = MATRIX.replace('m[1] = s * c', 'm[1] = m[3]')
    assert all(source.index('m[1] = m[3]') < source.index('m[3] = 0') for source in single_moves(reads_memory, 'f'))
    reads_global = 'extern float g;\n' + MATRIX.replace('m[1] = s * c', 'm[1] = g')
    assert all(source.index('m[1] = g') < source.index('m[3] = 0') for source in single_moves(reads_global, 'f'))
    other_array = MATRIX.replace('m[2] = -s', 'n[2] = -s').replace('float *m', 'float *m, float *n')
    assert all(source.index('n[2]') > source.index('m[1]') for source in single_moves(other_array, 'f'))


def test_locals_initialised_by_a_call_are_not_globals():
    source = '''void f(float *m, float x) {
    float c = cosf(x);
    float s = sinf(x);
    m[0] = c;
    m[1] = s;
    m[2] = c * s;
}'''
    moved = single_moves(source, 'f')
    assert any(candidate.index('m[2]') < candidate.index('m[0]') for candidate in moved)
