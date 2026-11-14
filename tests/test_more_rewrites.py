"""Rewrites moved from decompdecomp in 0.4.0: each proposes C only."""
from decomprepair import (
    callee_contracts,
    expression_recipes,
    initializer_clusters,
    layout_frontiers,
    loop_storage_shapes,
    ps1_gte,
    repair_tokens,
    switch_constant_dispatch,
    switch_tables,
)

LOOP = 'void f(void) { unsigned int i; i=0; do { use(i); i++; use(i); } while(i<4); }'


def test_loop_backedge_keeps_the_original_condition():
    family, source = loop_storage_shapes.variants(LOOP, 'f', arch='mips')[0]
    assert family == 'explicit_loop_backedge' and 'if (i<4) goto __repair_rows;' in source
    assert not loop_storage_shapes.variants(LOOP.replace('use(i); i++;', 'break; i++;'), 'f', arch='mips')


def test_recipes_bind_names_and_refuse_new_code():
    recipe = expression_recipes.template('int f(){return x + y;}', 'int f(){return y + x;}')
    assert expression_recipes.apply('int g(){return left + right;}', recipe) == 'int g(){return right + left;}'
    assert expression_recipes.apply('int g(){return left * right;}', recipe) is None
    assert expression_recipes.template('int f(){return x + y;}', 'int f(){return helper(x);}') is None


def test_tokens_are_lossless():
    text = 'int f(void){ /* a b */ return "x y" + 1; }'
    assert ''.join(repair_tokens.tokens(text)) == text


def test_layouts_borrow_whitespace_only():
    assert layout_frontiers.equivalent('int f(){return 1;}', 'int f() {\n  return 1;\n}')
    assert not layout_frontiers.equivalent('int f(){return 1;}', 'int f(){return 2;}')
    assert not layout_frontiers.safe('int f(){return __LINE__;}')


def test_switch_cases_follow_the_target_table():
    source = 'void f(int x){ switch(x){ case 1: a(); break; case 0: b(); break; } }'
    found = switch_tables.variants(source, 'f', [(0, [0x100, 0x200])])
    assert all(family == 'target_switch_order' for family, _ in found)
    assert switch_tables.value("'A'") == 65


def test_other_families_return_lists_and_leave_unrelated_code_alone():
    plain = 'int f(int a){ return a; }'
    assert switch_constant_dispatch.variants(plain, 'f') == []
    assert initializer_clusters.variants(plain, 'f') == []
    assert callee_contracts.type_name('unsigned int') == callee_contracts.type_name('u32') == 'u32'  # one spelling


def test_gte_header_is_fixed_macros():
    assert '#define' in ps1_gte.header() and '__asm__' in ps1_gte.header()
