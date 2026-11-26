from decomprepair import registry
from decomprepair.statement_across_call import FAMILY_CONDITION, FAMILY_HOIST, FAMILY_SINK, LIMIT, REPAIR, variants

HOIST = """s32 run(void *arg0) {
    s32 result;
    s32 mode;

    prepare();
    mode = *(s32 *)((s8 *)arg0 + 0xC0);
    result = 0;
    switch (mode) {
    case 1:
        result = go(arg0);
        break;
    }
    return result;
}
"""
SINK = """void clear(Obj *o) {
    o->flag = 0;
    notify(o);
    o->count = 3;
}
"""
CONDITION = """f32 near(Obj *o, f32 r) {
    o->m = 0;
    if (r <= measure(o, r)) {
        o->hit = 1;
    }
    return r;
}
"""
HEADER = 'f32 measure(Obj *, f32);\nvoid notify(Obj *);\n'


def kids(source, family=None, name='run', header=''):
    return [c for f, c in variants(source, name, header) if family in (None, f)]


def test_an_initialiser_after_a_call_and_a_load_is_written_above_them():
    out = kids(HOIST, FAMILY_HOIST)
    assert any(c.index('result = 0;') < c.index('prepare();') for c in out)
    assert all(c.count('result = 0;') == 1 for c in out)


def test_a_store_is_written_after_the_call_beside_it():
    out = kids(SINK, FAMILY_SINK, 'clear')
    assert any(c.index('notify(o);') < c.index('o->flag = 0;') for c in out)


def test_a_store_is_written_before_the_call_it_follows():
    out = kids(SINK, FAMILY_HOIST, 'clear')
    assert any(c.index('o->count = 3;') < c.index('notify(o);') for c in out)


def test_a_statement_is_not_moved_across_a_call_that_names_what_it_sets():
    source = 'void f(Obj *o) {\n    o->flag = 0;\n    notify(o->flag);\n}\n'
    assert not [c for c in kids(source, None, 'f') if c.index('notify') < c.index('o->flag = 0')]


def test_the_call_of_a_test_is_taken_into_a_local_above_the_store_before_it():
    out = kids(CONDITION, FAMILY_CONDITION, 'near', HEADER)
    assert out
    child = out[0]
    assert child.index('call_') < child.index('o->m = 0;') and '<= call_' in child and 'f32 call_' in child
    assert 'measure(o, r)' in child


def test_a_call_with_no_known_return_type_or_in_a_short_circuit_is_left_in_the_test():
    assert not kids(CONDITION, FAMILY_CONDITION, 'near', 'void measure(Obj *, f32);\n')
    assert not kids(CONDITION.replace('r <= measure(o, r)', 'r > 0 && r <= measure(o, r)'), FAMILY_CONDITION, 'near', HEADER)


def test_goto_and_volatile_leave_a_function_alone():
    assert not kids(SINK.replace('notify(o);', 'goto out;'), None, 'clear')


def test_it_is_registered_and_bounded():
    repair = registry.get('statement_across_call')
    assert repair and registry.problems(repair) == [] and set(REPAIR['families']) == {FAMILY_HOIST, FAMILY_SINK, FAMILY_CONDITION}
    assert len(variants(HOIST + SINK, 'run')) <= LIMIT


def test_a_compound_assignment_is_not_moved():
    # A 182-instruction N64 loader: `count *= 8;` was sunk below `f(.., count); end += count;` (its left side read as
    # `count *`, which neither statement names): the call then got `count`, not `count * 8`.
    source = ('void f(s32 *buf, s32 count) {\n    s32 end;\n\n    end = 0;\n    count *= 8;\n    g(buf, count);\n'
              '    end += count;\n    h(end);\n}\n')
    for op in ('*=', '+=', '-=', '|=', '&=', '<<=', '>>=', '^=', '/=', '%='):
        src = source.replace('count *= 8;', f'count {op} 8;')
        moved = [c for c in kids(src, None, 'f') if c.index(f'count {op} 8;') > c.index('g(buf')]
        assert not moved, op
