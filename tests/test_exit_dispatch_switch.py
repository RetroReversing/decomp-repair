"""A loop's `== K` guards and last `!= K2` guard, each ending in `continue`, written as the `switch` they were.

Synthetic shape of a 56-instruction N64 message thread (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mfp64`): its machine draft went
1126 -> 0 with this rewrite alone (exact judge, decompdecomp)."""
from decomprepair import exit_dispatch_switch as m
from decomprepair import registry

SOURCE = '''typedef short s16;
typedef int s32;
int check(void *);
void recv(s32 *);
extern s32 state[];
extern char pads[];

void serve(void)
{
    s32 msg;
    s16 kind;
    s32 slot;
    s32 other;

    for (;;)
    {
loop_2:
        recv(&msg);
        kind = (s16) msg;
        if (kind == 1) {
            if (check(pads) == 0) {
                state[msg] = kind;
            }
            continue;
        }
        other = msg * 0x68;
        do { if (kind != 2) {
            goto loop_2;
        } } while (0);
        if (check(pads + other) != 0) {
            continue;
        }
        state[msg] = 0;
        continue;
    break;
    }
}
'''


def texts(source=SOURCE, name='serve'):
    found = m.variants(source, name)
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_guards_become_one_switch():
    [text] = texts()
    assert 'switch (kind) {' in text and 'case 1:' in text and 'case 2:' in text
    assert 'goto' not in text and 'loop_2' not in text and 'do {' not in text
    body = text[text.index('case 2:'):]
    assert body.index('other = msg * 0x68;') < body.index('check(pads + other)')
    assert 'continue;\n            }' in body  # an exit in the middle of an arm stays
    assert text.count('break;') == 2


def test_guards_without_a_last_unequal_test_make_the_rest_the_default():
    source = '''void f(int);
int get(void);
void serve(void)
{
    int kind;

    for (;;) {
        kind = get();
        if (kind == 1) { f(1); continue; }
        if (kind == 4) { f(2); continue; }
        f(kind);
    }
}
'''
    [text] = texts(source)
    assert 'case 4:' in text and 'default:' in text


def test_a_void_function_that_returns():
    source = '''void f(int);
void step(int kind)
{
    if (kind == 1) {
        f(1);
        return;
    }
    if (kind != 2) {
        return;
    }
    f(2);
}
'''
    [text] = texts(source, 'step')
    assert 'switch (kind) {' in text and 'return' not in text


def test_left_alone_when_the_meaning_would_change():
    # the stage is read after the dispatch's arm, in the first arm
    assert texts(SOURCE.replace('state[msg] = kind;', 'state[msg] = other;')) == []
    # the stage calls
    assert texts(SOURCE.replace('other = msg * 0x68;', 'other = check(pads);')) == []
    # a `break` that leaves the loop would leave the switch instead
    assert texts(SOURCE.replace('state[msg] = 0;', 'if (msg) break;\n        state[msg] = 0;')) == []
    # a goto elsewhere than the loop's head
    assert texts(SOURCE.replace('goto loop_2;', 'goto done;')) == []
    # a single guard with no `!=` test: nothing to dispatch
    assert texts('void f(void);\nvoid s(int k)\n{\n    if (k == 1) {\n        return;\n    }\n    f();\n}\n', 's') == []


def test_declared_for_every_caller():
    repair = registry.get('exit_dispatch_switch')
    assert repair is not None and registry.problems(repair) == []
