from decomprepair.target_local_repairs import call_result_pass


def test_repeated_call_slots_offer_reuse_without_a_full_proposal_pool():
    source = """int f(void) {
    int first;
    int last;
    first = read();
    consume(first);
    last = read();
    return last;
}"""
    choices = call_result_pass(source, 'f')
    assert any(family == 'call_result_reuse' and 'return first;' in child for family, child in choices)
    assert not call_result_pass(source.replace('last = read()', 'last = other()'), 'f')
    assert not call_result_pass(source.replace('int last;', 'volatile int last;'), 'f')
