"""Branches whose arms jump2 merged, written as whole arms (a 1300-instruction controller routine, 10695 -> 4645)."""
from decomprepair.branch_join_arm_rewrites import FAMILY_CHAIN, FAMILY_SWITCH, FAMILY_TESTS, REPAIR, variants

TESTS = """void update(Obj *o)
{
    f32 var_fv0_2;
    s32 var_condition_bit_2;
    f32 f;
    f = o->speed;
    if (f < 0.0f)
    {
        var_fv0_2 = f + 0.02f;
        var_condition_bit_2 = var_fv0_2 > 0.0f;
    }
    else
    {
        var_fv0_2 = f - 0.02f;
        var_condition_bit_2 = var_fv0_2 < 0.0f;
    }
    o->speed = var_fv0_2;
    if (var_condition_bit_2)
    {
        o->speed = 0.0f;
    }
    o->done = 1;
}
"""

CHAIN = """void paint(s32 kind, Node *n)
{
    s32 var_v1;
    switch (kind)
    {
      case 2:
        var_v1 = 0x3F3FFFFF;
        break;

      case 1:
        var_v1 = 0x3FFF3FFF;
        break;

      default:
        var_v1 = 0xFF0000FF;
        break;

    }

    n->color = var_v1;
    n->flags = (n->flags & ~0xFC) | 0x10;
    draw(n);
}
"""

SWITCH = """void clamp(Obj *o, s16 mode)
{
    if (!(mode != 2))
    {
        o->a = 1;
    }
    else
      if (mode != 5)
    {
        o->b = 2;
    }
    else
    {
        o->c = 3;
    }
    done(o);
}
"""


def children(source, name, family):
    return [text for fam, text in variants(source, name) if fam == family]


def squash(text):
    return ' '.join(text.split())


def test_the_test_goes_into_each_arm_with_the_statements_after_the_join():
    found = children(TESTS, 'update', FAMILY_TESTS)
    assert len(found) == 1
    child = squash(found[0])
    assert 'condition_bit' not in child
    assert ('var_fv0_2 = f + 0.02f; o->speed = var_fv0_2; if (var_fv0_2 > 0.0f) { o->speed = 0.0f; } }' in child)
    assert ('var_fv0_2 = f - 0.02f; o->speed = var_fv0_2; if (var_fv0_2 < 0.0f) { o->speed = 0.0f; } }' in child)
    assert child.count('o->speed = var_fv0_2;') == 2
    assert child.endswith('o->done = 1; }')


def test_a_negated_test_keeps_its_negation():
    child = children(TESTS.replace('if (var_condition_bit_2)', 'if (!var_condition_bit_2)'), 'update', FAMILY_TESTS)[0]
    assert 'if (!(var_fv0_2 > 0.0f))' in child


def test_an_operand_written_between_keeps_the_flag():
    source = TESTS.replace('    o->speed = var_fv0_2;\n', '    var_fv0_2 = o->other;\n')
    assert children(source, 'update', FAMILY_TESTS) == []


def test_a_memory_comparison_does_not_move_past_a_store():
    source = (TESTS.replace('var_condition_bit_2 = var_fv0_2 > 0.0f;', 'var_condition_bit_2 = o->limit > 0.0f;')
              .replace('var_condition_bit_2 = var_fv0_2 < 0.0f;', 'var_condition_bit_2 = o->limit < 0.0f;'))
    assert children(source, 'update', FAMILY_TESTS) == []


def test_the_switch_becomes_an_ascending_chain_with_the_statements_in_every_arm():
    found = children(CHAIN, 'paint', FAMILY_CHAIN)
    assert found
    first = squash(found[0])
    assert 'switch' not in first
    assert first.index('if (kind == 1)') < first.index('else if (kind == 2)') < first.index('else {')
    # the next plain statements (the call too, at most three) are copied into every arm
    assert first.count('n->color = var_v1;') == 3
    assert first.count('n->flags = (n->flags & ~0xFC) | 0x10;') == 3
    assert any(squash(c).count('draw(n);') == 1 and squash(c).count('n->flags') == 6 for c in found)


def test_a_switch_with_more_than_assignments_is_left_alone():
    source = CHAIN.replace('var_v1 = 0x3FFF3FFF;\n', 'var_v1 = 0x3FFF3FFF;\n        n->x = 1;\n')
    assert children(source, 'paint', FAMILY_CHAIN) == []


def test_two_switches_are_rewritten_together_first():
    block = CHAIN[CHAIN.index('    switch'):CHAIN.index('    draw(n);')]
    source = CHAIN.replace('    draw(n);\n', '    draw(n);\n' + block + '    draw(n);\n')
    found = children(source, 'paint', FAMILY_CHAIN)
    assert source.count('switch') == 2
    assert 'switch' not in found[0]
    assert any(c.count('switch') == 1 for c in found)


def test_the_negated_chain_is_a_switch_with_its_default_first():
    found = children(SWITCH, 'clamp', FAMILY_SWITCH)
    assert len(found) == 2
    first = squash(found[0])
    assert first.index('default:') < first.index('case 2:') < first.index('case 5:')
    assert 'default: o->b = 2; break; case 2: o->a = 1; break; case 5: o->c = 3; break; }' in first
    second = squash(found[1])
    assert second.index('case 2:') < second.index('case 5:') < second.index('default:')


def test_a_chain_on_two_values_or_with_a_break_is_left_alone():
    assert children(SWITCH.replace('mode != 5', 'other != 5'), 'clamp', FAMILY_SWITCH) == []
    assert children(SWITCH.replace('o->b = 2;', 'o->b = 2; break;'), 'clamp', FAMILY_SWITCH) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert set(REPAIR['families']) == {FAMILY_TESTS, FAMILY_CHAIN, FAMILY_SWITCH}
