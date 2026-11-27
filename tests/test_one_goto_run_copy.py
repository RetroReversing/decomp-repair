"""one_goto_run_copy and chain_arm_check_goto: the shared success tail of a per-player if chain."""
from decomprepair import chain_arm_check_goto, one_goto_run_copy, one_web_split, registry

CHAIN = '''void f(Obj *obj) {
    s32 ok;

    if (G != 0) {
        if (obj->player == 0) {
            ok = 0;
            if (A != 0) {
                ok = 1;
            }
            if (ok) {
                goto success;
            }
        } else if (obj->player == 1) {
            ok = 0;
            if (B != 0) {
                ok = 1;
            }
            if (ok) {
                goto success;
            }
        } else if (obj->player == 2) {
            ok = 0;
            if (C != 0) {
                ok = 1;
            }
            if (ok) {
                goto success;
            }
        } else {
            return;
        }
        goto fail;
success:
        start(obj);
        if (S != 2) {
            T[obj->player] = 1;
            slide(obj, 300, 499);
        }
        return;
    }
fail:
    obj->state = 99;
}
'''


def _flat(text):
    return ' '.join(text.split())


def test_one_goto_takes_its_own_copy_of_the_return_run():
    children = one_goto_run_copy.variants(CHAIN, 'f')
    assert [family for family, _ in children] == ['one_goto_run_copy'] * 3
    first = _flat(children[0][1])
    # the last goto holds the whole run; the others still jump to the label, which stays
    assert first.count('slide(obj, 300, 499);') == 2
    assert first.count('goto success;') == 2
    assert 'success:' in first
    assert first.index('goto success;') < first.index('slide(obj, 300, 499);')
    assert 'ok = 1; } if (ok) { start(obj); if (S != 2) { T[obj->player] = 1; slide(obj, 300, 499); } return; }' in first


def test_one_goto_declines_a_single_goto_and_a_run_without_return():
    single = 'void f(void) { if (a) { goto out; } b(); out: c(); return; }'
    falls = 'void f(void) { if (a) { goto out; } if (d) { goto out; } b(); out: c(); }'
    shadowed = 'void f(void) { if (a) { s32 x; goto out; } if (d) { goto out; } out: c(x); return; }'
    for source in (single, falls, shadowed):
        assert one_goto_run_copy.variants(source, 'f') == []


def test_a_later_arm_jumps_into_an_earlier_arms_check():
    children = chain_arm_check_goto.variants(CHAIN, 'f')
    assert children and {family for family, _ in children} == {'chain_arm_check_goto'}
    wanted = [text for _, text in children
              if _flat(text).count('goto check_0;') == 1 and _flat(text).index('check_0: if (ok)') < _flat(text).index('player == 1')
              and _flat(text).index('goto check_0;') > _flat(text).index('player == 2')]
    assert wanted
    assert _flat(wanted[0]).count('if (ok)') == 2


def test_arm_endings_that_use_an_arm_local_are_left():
    source = ('void f(s32 p) { if (p == 0) { s32 v = a(); if (v) { goto out; } } else if (p == 1) '
              '{ s32 v = b(); if (v) { goto out; } } c(); out: d(); }')
    assert chain_arm_check_goto.variants(source, 'f') == []


def test_one_web_alone_is_offered():
    texts = [_flat(text) for _, text in one_web_split.variants(CHAIN, 'f')]
    assert any('ok_1 = 0;' in t and t.count('ok = 0;') == 2 for t in texts)


def test_declared_to_the_registry():
    names = {repair.module for repair in registry.declared()}
    assert {'one_goto_run_copy', 'chain_arm_check_goto', 'one_web_split'} <= {n.rsplit('.', 1)[-1] for n in names}
