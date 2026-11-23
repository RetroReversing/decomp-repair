from decomprepair.weight_ladder_trim import FULL, ONE, PAIR, variants

SOURCE = """void walk(Obj *arg0, s32 arg1) {
    s32 a;
    s32 b;
    a = arg1 * 16;
    do { do { do { b = *(s16 *)((u8 *)table + a); } while (0); } while (0); } while (0);
    do { use(a, b); } while (0);
    if (b) {
        do { more(a); } while (0);
    }
}
"""


def _of(family, source=SOURCE):
    return [child for kind, child in variants(source, 'walk') if kind == family]


def test_a_chain_of_scopes_round_one_statement_is_removed():
    children = _of(FULL)
    assert any('    b = *(s16 *)((u8 *)table + a);\n' in c and 'do { do { do { b' not in c for c in children)
    assert any('        more(a);' in c for c in children)
    assert len(children) == 3  # the three chains: b's, use()'s and more()'s


def test_a_deep_chain_can_also_lose_just_one_scope():
    children = _of(ONE)
    assert len(children) == 1
    assert 'do { do { b = *(s16 *)((u8 *)table + a); } while (0); } while (0);' in children[0]


def test_a_scope_that_holds_a_brace_or_a_label_stays():
    source = SOURCE.replace('do { use(a, b); } while (0);', 'do { if (a) { use(a, b); } } while (0);')
    assert not any('if (a) { use' in c and 'do { if (a)' not in c for c in _of(FULL, source))


def test_the_pair_removes_a_chain_and_writes_the_call_scope_as_a_goto_that_never_runs():
    pairs = _of(PAIR)
    assert pairs
    assert all('goto' in c for c in pairs)
    assert any('    b = *(s16 *)((u8 *)table + a);\n' in c for c in pairs)


def test_it_declares_itself():
    from decomprepair import registry
    assert 'weight_ladder_trim' in {repair.module for repair in registry.declared()}
