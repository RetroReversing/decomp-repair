"""A run of exiting `if (v == K)` guards written as the `switch` it was, the rest of the region as its `default:`.

Synthetic shape of a 376-instruction enemy state machine (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mfp32`): its two runs on a
call's result went 2038 -> 40 as `switch`es (exact judge, decompdecomp)."""
from decomprepair import guard_exit_switch as m
from decomprepair import registry

SOURCE = '''typedef int s32;
typedef struct Obj { s32 sub; s32 state; s32 timer; } Obj;
s32 check(Obj *);
void start(Obj *, s32);

void step(Obj *o)
{
    s32 r;

    switch (o->state) {
    case 0:
        o->state = 1;
        break;
    case 1:
        r = check(o);
        if (r == 1) {
            o->state = 3;
            start(o, 0x36);
            break;
        }
        if (r == 2) {
            start(o, 0x35);
            o->state = 3;
            break;
        }
        switch (o->sub) {
        case 0:
            o->sub = 1;
            break;
        }
        break;
    case 2:
        o->timer = 0;
        break;
    }
}
'''


def texts(source=SOURCE, name='step'):
    found = m.variants(source, name)
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_guards_become_a_switch_whose_default_is_the_rest_of_the_arm():
    plain = texts()[0]
    assert '''        r = check(o);
        switch (r) {
        case 1:
            o->state = 3;
            start(o, 0x36);
            break;
        case 2:
            start(o, 0x35);
            o->state = 3;
            break;
        default:
            switch (o->sub) {
            case 0:
                o->sub = 1;
                break;
            }
            break;
        }
        break;
    case 2:''' in plain


def test_the_call_itself_is_switched_on_when_nothing_else_reads_the_result():
    inline = texts()[1]
    assert '        switch (check(o)) {\n        case 1:' in inline
    assert 'r = check(o);' not in inline
    assert 's32 r;' not in inline


def test_a_result_the_rest_reads_keeps_its_local():
    found = texts(SOURCE.replace('o->sub = 1;', 'o->sub = r;'))
    assert len(found) == 1 and 'switch (r) {' in found[0] and 'o->sub = r;' in found[0]


def test_two_runs_are_also_rewritten_together():
    source = SOURCE.replace('''    case 2:
        o->timer = 0;
        break;''', '''    case 2:
        r = check(o);
        if (r == 1) {
            o->state = 3;
            start(o, 0x36);
            break;
        }
        if (r == 2) {
            start(o, 0x35);
            break;
        }
        o->timer = 0;
        break;''')
    found = texts(source)
    assert found[0].count('switch (r) {') == 2
    assert found[1].count('switch (check(o)) {') == 2 and 's32 r;' not in found[1]


def test_return_guards_at_the_end_of_a_function():
    source = '''typedef int s32;
s32 check(s32);
void start(s32);

void run(s32 v)
{
    if (v == 3) {
        start(1);
        return;
    }
    if (v == 5) {
        start(2);
        return;
    }
    start(v + 1);
}
'''
    (text,) = texts(source, 'run')
    assert '''    switch (v) {
    case 3:
        start(1);
        return;
    case 5:
        start(2);
        return;
    default:
        start(v + 1);
    }
}''' in text


def test_guards_left_alone():
    # A single guard is an `if`; a `break` outside a `switch`, an `else`: no `switch`.
    assert texts(SOURCE.replace('''        if (r == 2) {
            start(o, 0x35);
            o->state = 3;
            break;
        }
''', '')) == []
    assert texts(SOURCE.replace('''        if (r == 2) {
            start(o, 0x35);
            o->state = 3;
            break;
        }''', '''        else if (r == 2) {
            start(o, 0x35);
            o->state = 3;
            break;
        }''')) == []
    loop = '''typedef int s32;
s32 check(s32);
void run(s32 v)
{
    while (v) {
        if (v == 3) {
            break;
        }
        if (v == 5) {
            break;
        }
        v = check(v);
    }
}
'''
    assert texts(loop, 'run') == []


def test_it_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'guard_exit_switch')
    assert registry.problems(repair) == []
