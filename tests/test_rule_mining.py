"""Rules learnt from matches (rule_mining.py): one statement-sized change, generalised, that reproduces itself."""
from decomprepair import rule_mining as mining
from decomprepair import rules

BEFORE = '''s32 f(void) {
    return *(s32 *)0x1000;
}
'''
AFTER = BEFORE.replace('(s32 *)', '(volatile s32 *)')


def _apply(pair, source, name):
    return rules.apply(rules.compile_rule(mining.rule(*pair)), source, name)


def test_a_change_is_learnt_and_applies_to_another_function():
    pair = mining.rewrite(BEFORE, AFTER, 'f')
    assert pair == ('return * ( s32 * ) #0 ;', 'return * ( volatile s32 * ) #0 ;')
    other = 'int g(void) {\n    return *(s32*) 0x80;\n}\n'
    [(family, source)] = _apply(pair, other, 'g')
    assert family == mining.identifier(*pair)
    assert 'return * ( volatile s32 * ) 0x80 ;' in source
    assert rules.problems(mining.rule(*pair, archs=('mips',))) == []


def test_slots_keep_names_that_repeat_together_and_may_swap():
    before = 'void f(void) {\n    s32 a;\n    s32 b;\n    use(a, b);\n}\n'
    after = 'void f(void) {\n    s32 b;\n    s32 a;\n    use(a, b);\n}\n'
    pair = mining.rewrite(before, after, 'f')
    assert pair == ('s32 $0 ; s32 $1 ;', 's32 $1 ; s32 $0 ;')
    [(_, source)] = _apply(pair, 'void g(void) {\n    s32 left;\n    s32 right;\n}\n', 'g')
    assert source.index('right') < source.index('left')


def test_comments_and_layout_are_not_a_change():
    reprinted = 'void f(int *p)\n{\n  *p = 1; /* kept */\n}\n'
    assert mining.rewrite('void f(int *p) { *p = 1; }\n', reprinted, 'f') is None


def test_changes_a_rule_cannot_make_again_are_refused():
    body = 'void f(s32 x) {\n    g(x);\n}\n'
    assert mining.rewrite(body, body.replace('g(x)', 'g(x + extra)'), 'f') is None    # a new name
    assert mining.rewrite(body, body.replace('s32 x', 'u32 x'), 'f') is None          # outside the body
    assert mining.rewrite('void f(void) { a = b; }\n', 'void f(void) { b = a; }\n', 'f') is None   # says nothing
    two = 'void f(void) {\n    s32 a = 1;\n    g(); h(); i(); j();\n    s32 b = 2;\n}\n'
    assert mining.rewrite(two, two.replace('s32 a', 'u32 a').replace('s32 b', 'u32 b'), 'f') is None   # two changes
    text = 'void f(void) {\n    puts("a", 1);\n}\n'
    assert mining.rewrite(text, text.replace('1', '0'), 'f') is None                  # strings are blanked in rules
