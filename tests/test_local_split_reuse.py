import re

from decomprepair import registry
from decomprepair.local_split_reuse import (
    FAMILY_BASE,
    FAMILY_CURSOR,
    FAMILY_SPLIT,
    FAMILY_TEST,
    LIMIT,
    REPAIR,
    variants,
)

SPLIT = """f32 step(Obj *o) {
    f32 d;
    f32 acc;
    s32 flag;

    d = near(o);
    if (d < 5.0f) {
        return 1.0f;
    }
    if (flag) {
        d = o->x;
        acc = d * 2.0f;
    } else {
        d = far(o);
        acc = d + 1.0f;
    }
    return acc + d;
}
"""


def kids(source, family=None, name='step', header=''):
    return [c for f, c in variants(source, name, header) if family in (None, f)]


def test_the_first_range_of_a_reused_local_gets_a_local_of_its_own_declared_after_the_others():
    first = next(c for c in kids(SPLIT, FAMILY_SPLIT) if 'd2 = near(o);' in c)
    assert 'if (d2 < 5.0f)' in first and 'f32 d2;' in first
    assert first.index('f32 d2;') > first.index('s32 flag;') and 'd = o->x;' in first


def test_the_second_range_is_offered_too():
    second = [c for c in kids(SPLIT, FAMILY_SPLIT) if 'd2 = o->x;' in c]
    assert second and 'acc = d2 * 2.0f;' in second[0] and 'd = near(o);' in second[0]


def test_a_conditional_definition_that_leaves_the_first_value_live_is_not_split():
    source = SPLIT.replace('    } else {\n        d = far(o);\n        acc = d + 1.0f;\n    }', '    }')
    assert not [c for c in kids(source, FAMILY_SPLIT) if 'd2 = near(o);' in c]


def test_a_loop_that_reads_the_local_before_its_definition_carries_it_round():
    source = """s32 f(void) {
    s32 d;
    s32 i;

    d = 0;
    for (i = 0; i < 3; i++) {
        use(d);
        d = g(i);
    }
    d = h();
    return d;
}
"""
    assert not [c for c in kids(source, FAMILY_SPLIT, 'f') if 'd2 = g(i)' in c]


def test_an_address_taken_local_and_a_function_with_goto_are_left_alone():
    assert not kids(SPLIT.replace('d = near(o);', 'd = near(o); keep(&d);'), FAMILY_SPLIT)
    assert not kids(SPLIT.replace('return 1.0f;', 'goto out;'), None)


def test_a_loop_cursor_set_from_a_call_above_the_loop_takes_its_own_local():
    source = """void walk(void) {
    Obj *o;
    Obj *end;
    Tri *t;

    o = first(0);
    end = last(0);
    for (; o <= end; o++) {
        visit(o);
    }
}
"""
    out = kids(source, FAMILY_CURSOR, 'walk')
    assert any('p1 = first(0);' in c and 'for (o = p1; o <= end; o++)' in c for c in out)
    beside = next(c for c in out if 'Obj *p1;' in c and c.index('Obj *p1;') < c.index('Tri *t;'))
    assert beside.index('Obj *p1;') > beside.index('Obj *end;')


def test_a_call_result_that_is_only_the_base_of_a_store_is_held_in_a_local():
    source = """void put(void *arg0) {
    void *temp_v0;

    temp_v0 = make(NULL);
    use(temp_v0);
    M2C_FIELD(make(arg0), void **, 0x9C) = &cb;
}
"""
    header = 'void *make(void *);\n'
    out = kids(source, FAMILY_BASE, 'put', header)
    assert any('temp_v0 = make(arg0);\n    M2C_FIELD(temp_v0, void **, 0x9C)' in c for c in out)
    assert any(re.search(r'void \*temp_\d+;', c) for c in out)


def test_a_call_in_a_test_that_a_statement_assigns_to_a_local_is_assigned_there():
    source = """void near(Obj *a) {
    f32 dist;

    dist = sqrtf(a->x * a->x);
    if (k < 3.0f) {
        if (!(lim < sqrtf(a->x * a->x))) {
            a->go = 1;
        }
    }
    use(dist);
}
"""
    out = kids(source, FAMILY_TEST, 'near')
    assert out and '!(lim < (dist = sqrtf(a->x * a->x)))' in out[0]


def test_it_is_a_registered_repair_with_a_bounded_child_count():
    assert registry.get('local_split_reuse') and registry.problems(registry.get('local_split_reuse')) == []
    assert set(REPAIR['families']) == {FAMILY_SPLIT, FAMILY_CURSOR, FAMILY_BASE, FAMILY_TEST}
    assert len(variants(SPLIT, 'step')) <= LIMIT


def test_second_range_renames_the_reads_of_the_next_definition():
    # A 97-instruction N64 loader: `size = n; ...; size = f(buf); size = (size & 0x3F) ? ... : size;`. The second
    # range ends at the next definition, whose right side reads it: renaming only `size = f(buf)` left the rounding
    # reading the first range's value (an unfaithful child that scored better by accident).
    src = '''s32 f(s32 n, u8 *buf) {
    s32 size;
    s32 end;

    size = n;
    buf = g(size + n);
    size = h(n, buf);
    size = (size & 0x3F) ? (size & ~0x3F) + 0x40 : size;
    end = k(buf + size);
    return end;
}
'''
    for fam, child in variants(src, 'f'):
        if fam != FAMILY_SPLIT or 'size2 = h(n, buf);' not in child:
            continue
        assert 'size = (size2 & 0x3F) ? (size2 & ~0x3F) + 0x40 : size2;' in child, child


CARRIED_ROUND = """void f(s32 *p) {
    s32 i;
    s32 off;

    i = 0;
    off = 0 * 2;
    do {
        g(off + p);
        i += 1;
        off = i * 2;
    } while (i < 16);
}
"""


def test_a_value_a_loop_carries_to_a_use_is_not_renamed_apart_from_it():
    assert not [c for f, c in variants(CARRIED_ROUND, 'f', '') if f == FAMILY_SPLIT]
