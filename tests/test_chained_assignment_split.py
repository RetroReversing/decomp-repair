from decomprepair import registry
from decomprepair.chained_assignment_split import FAMILY, REPAIR, variants

CHAIN = """void f(Rec *p, f32 t) {
    p->a = p->b = t;
    use(p->a);
}
"""
SPLIT = """void f(Rec *p, f32 t) {
    p->b = t;
    p->a = p->b;
    use(p->a);
}
"""


def kids(source):
    return [c for fam, c in variants(source, 'f') if fam == FAMILY]


def test_a_chain_becomes_a_read_back_and_a_second_store_of_the_value():
    out = kids(CHAIN)
    assert any('p->b = t;\n    p->a = p->b;' in c for c in out)
    assert any('p->b = t;\n    p->a = t;' in c for c in out)


def test_two_adjacent_statements_become_a_chain():
    out = kids(SPLIT)
    assert out == [CHAIN]


def test_a_call_on_the_right_is_not_repeated():
    assert not kids(CHAIN.replace('= t;', '= g(t);'))


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}


FANOUT = """void g(Obj *o) {
    t = o->a;
    o->b = t;
    o->c = t;
    d = h(o, 0, t);
}
"""


def test_a_temporary_fanned_out_to_two_fields_is_loaded_twice_and_read_back_from_the_last():
    out = kids(FANOUT.replace('void g', 'void f'))
    assert any('o->b = o->a;\n    o->c = o->a;\n    d = h(o, 0, o->c);' in c for c in out)
    assert any('d = h(o, 0, o->b);' in c for c in out)


def test_a_later_use_of_the_temporary_past_the_window_blocks_it():
    late = FANOUT.replace('void g', 'void f').replace('}\n', '    x = 1;\n    y = 2;\n    z = 3;\n    w = t;\n}\n')
    assert not any('o->b = o->a;' in c for c in kids(late))
