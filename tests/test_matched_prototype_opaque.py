"""Identical opaque pointer arguments do not hide a selected integer return type."""
from decomprepair import matched_prototype_repairs as repair


def test_opaque_pointer_arguments_allow_return_type_candidate():
    source = 'int gain(void *, void *); short f(void *a, void *b) { return gain(a, b); }'
    callee = 'short gain(void *state, void *player) { return 1; }'
    result = repair.variants(source, 'f', callees=callee)
    assert result == [(repair.FAMILY, source.replace('int gain', 'short gain'))]


def test_opaque_pointer_argument_must_match_and_be_named_in_definition():
    source = 'int gain(void *, void *); short f(void *a, void *b) { return gain(a, b); }'
    for params in ('void *state, int player', 'int *state, void *player', 'void *, void *player',
                   'void **state, void *player', 'void (*state)(void), void *player'):
        assert not repair.variants(source, 'f', callees=f'short gain({params}) {{ return 1; }}')
