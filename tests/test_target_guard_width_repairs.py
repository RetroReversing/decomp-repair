from decomprepair import target_guard_width_repairs as repairs


def propose(source,rewrite,witness=True):
    return [text for _,text in repairs.variants(source,'f','',[(rewrite,witness)])]


def test_pointer_snapshot_requires_an_unescaped_automatic_binding():
    source = 'struct Node { int first, second; }; int f(struct Node *p) { if (p) { return p->first+p->second; } return 0; }'
    [new] = propose(source,repairs.nonnull_pointer)
    assert 'struct Node *repair_body_pointer = p;' in new
    assert not propose(source.replace('int f(struct Node *p)','struct Node *p; int f(void)'),repairs.nonnull_pointer)
    assert not propose(source.replace('if (p)','use(&p); if (p)'),repairs.nonnull_pointer)


def test_float_reload_preserves_comparison_order_and_short_circuit():
    source = ('struct S { float x,y; }; int f(struct S *p,float a,float b) { '
              'if (p->x < a || b < p->x) { return 1; } return 0; }')
    new, explicit = propose(source,repairs.fallthrough_float)
    assert 'if (repair_compare_field < a || (repair_compare_field = p->x, b < repair_compare_field))' in new
    assert 'goto repair_compare_join; repair_compare_field = p->x;' in explicit
    assert not propose(source.replace('b < p->x','b < p->y'),repairs.fallthrough_float)


def test_literal_is_only_a_replacement_for_the_bitwise_operand():
    source = 'extern int mask; unsigned int f(unsigned int word) { return word | (unsigned int)&mask; }'
    evidence = {('mask',0xa0000000)}
    [new] = propose(source,repairs.mask_literal,evidence)
    assert 'return word | 0xA0000000U;' in new
    assert not propose(source.replace('word |','word +'),repairs.mask_literal,evidence)
