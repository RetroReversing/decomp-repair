"""A counter stepped at the end of every path of an endless loop, written as the `for` step."""
from decomprepair import loop_step_fold as m
from decomprepair import registry

# The shape of a menu builder: an early step before a release call, a `goto` to the shared step that ends the other arm.
FORKED = '''void f(void) {
    s32 *entry;
    s32 off;
    s32 first;
    s32 i;

    i = 2;
    for (;;) {
        if ((i & 0xFFFF) >= (count(0, 1) & 0xFFFF) + 2) {
            break;
        }
        off = (i & 0xFFFF) * 8;
        first = spawn(kind);
        entry = off + table;
        *entry = first;
        if (first != 0) {
            entry[1] = spawn(kind);
            if (entry[1] == 0) {
                i += 1;
                release(*(s32 *)((s8 *)table + off));
            } else {
                setup(entry, i & 0xFF);
                goto step;
            }
        } else {
step:
            i += 1;
        }
    }
    done();
}
'''


def test_forked_steps_become_the_for_step():
    [(family, out)] = m.variants(FORKED, 'f')
    assert family == 'loop_step_fold'
    assert 'for (;; i += 1) {' in out
    assert 'goto' not in out and 'step:' not in out
    assert out.count('i += 1') == 1
    assert 'release(*(s32 *)((s8 *)table + off));' in out and 'setup(entry, i & 0xFF);' in out


def test_while_one_and_increment_spellings():
    src = '''void f(void) {
    s32 i;

    i = 0;
    while (1) {
        if (i >= n) {
            break;
        }
        use(table[i]);
        i++;
    }
}
'''
    [(_, out)] = m.variants(src, 'f')
    assert 'for (;; i += 1) {' in out and 'i++' not in out and 'use(table[i]);' in out


def test_trailing_statements_that_read_the_counter_stop_the_fold():
    src = FORKED.replace('release(*(s32 *)((s8 *)table + off));', 'release(i);')
    assert m.variants(src, 'f') == []


def test_a_path_without_a_step_stops_the_fold():
    src = FORKED.replace('        } else {\nstep:\n            i += 1;\n        }', '        }')
    src = src.replace('                goto step;\n', '')
    assert m.variants(src, 'f') == []


def test_a_path_that_leaves_the_loop_needs_no_step():
    src = FORKED.replace('                i += 1;\n                release(', '                release(')
    src = src.replace('                release(*(s32 *)((s8 *)table + off));\n',
                      '                release(*(s32 *)((s8 *)table + off));\n                return;\n')
    [(_, out)] = m.variants(src, 'f')
    assert 'for (;; i += 1)' in out and 'return;' in out


def test_continue_and_address_taken_counters_are_left_alone():
    src = FORKED.replace('first = spawn(kind);', 'first = spawn(kind);\n        if (first == 7) {\n            continue;\n        }')
    assert m.variants(src, 'f') == []
    assert m.variants(FORKED.replace('done();', 'keep(&i);'), 'f') == []


def test_a_goto_from_outside_the_body_stops_the_fold():
    src = FORKED.replace('    i = 2;', '    if (early) {\n        goto step;\n    }\n    i = 2;')
    assert m.variants(src, 'f') == []


def test_the_family_declares_itself():
    assert m.REPAIR['variants'] is m.variants and 'loop_step_fold' in m.REPAIR['families']
    [repair] = [r for r in registry.declared() if r.module == 'loop_step_fold']
    assert registry.problems(repair) == []
