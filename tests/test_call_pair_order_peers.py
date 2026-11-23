"""The odd one of several call pairs turned round to its peers' order."""
from decomprepair import call_pair_order_peers as m
from decomprepair.registry import declared


def arm(first, second, k):
    return f'''    if (m == {k}) {{
        a{k} = size(arg_{first});
        b{k} = size(arg_{second});
        use(a{k}, b{k});
    }}
'''


def src(orders):
    body = ''.join(arm(*o, k) for k, o in enumerate(orders))
    return 'void f(s32 m) {\n' + body + '}\n'


def kids(source):
    return [t for fam, t in m.variants(source, 'f') if fam == m.FAMILY]


def test_the_odd_pair_is_turned_round():
    out = kids(src([('h', 'w'), ('h', 'w'), ('w', 'h'), ('h', 'w')]))
    assert len(out) == 1
    assert out[0].index('size(arg_h)', out[0].index('m == 2')) < out[0].index('size(arg_w)', out[0].index('m == 2'))
    assert 'b2 = size(arg_h);\n        a2 = size(arg_w);' in out[0]


def test_every_odd_pair_as_one_more_child():
    out = kids(src([('h', 'w'), ('w', 'h'), ('h', 'w'), ('h', 'w'), ('w', 'h')]))
    assert len(out) == 3
    assert out[-1].count('size(arg_h);\n') == 5 and out[-1].count('b1 = size(arg_h)') == 1


def test_a_tie_or_too_few_pairs_is_left():
    assert kids(src([('h', 'w'), ('w', 'h')])) == []
    assert kids(src([('h', 'w'), ('w', 'h'), ('h', 'w'), ('w', 'h')])) == []


def test_it_declares_itself():
    assert any(r.module == 'call_pair_order_peers' for r in declared())
