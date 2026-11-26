"""Calls fitted to the header's prototypes: proposals only, judged by the caller."""
from decomprepair import call_arity, registry


def test_extra_arguments_are_dropped_and_missing_ones_passed_as_zero():
    header = 'void draw(s32 a, s32 b);\nvoid reset(void);\ns32 add3(s32 a, s32 b, s32 c);\n'
    source = 'void f(s32 x) { draw(x, g(x, 1), 3); reset(x); x = add3(x, 2); }'
    assert call_arity.fit(source, 'f', header) == 'void f(s32 x) { draw(x, g(x, 1)); reset(); x = add3(x, 2, 0); }'


def test_nothing_without_a_fixed_plain_prototype_or_when_counts_agree():
    source = 'void f(s32 x) { draw(x); }'
    assert call_arity.fit(source, 'f', 'void draw(s32 a);') == ''
    assert call_arity.fit(source, 'f', 'void draw();') == ''  # unspecified in C
    assert call_arity.fit(source, 'f', 'void draw(Thing a, s32 b);') == ''  # a typedef this reader doesn't know
    assert call_arity.fit(source, 'f', '#define X 1\nvoid draw(s32 a, s32 b);') == ''
    assert call_arity.fit('void f(s32 draw) { draw(1); }', 'f', 'void draw(s32 a, s32 b);') == ''


def test_declared_for_the_registry():
    entry = registry.get('call_arity')
    assert entry is not None and registry.problems(entry) == []
    assert call_arity.variants('void f(void) { draw(1); }', 'f', 'void draw(s32 a, s32 b);') == [
        ('call_arity', 'void f(void) { draw(1, 0); }')]
