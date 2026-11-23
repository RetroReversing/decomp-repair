"""Which loops share a counter variable: a loop's own counter, two counters merged, a loop moved, two traded."""
import re

from decomprepair import loop_counter_roles_repairs as h

PRELUDE = '''typedef int s32;
typedef short s16;
typedef unsigned char u8;
extern s32 reader(void *, s32);
extern u8 A[], B[], C[];
'''
# m2c-style loops: `i` counts two do-while loops, `j` a goto loop and `k` a while loop
SOURCE = PRELUDE + '''
void f(s32 n) {
    s32 i;
    s32 j;
    s32 k;

    i = 0;
    do {
        A[i] = reader(A, 1);
        i += 1;
    } while (i < 4);
    j = 0;
loop_1:
    B[j] = reader(B, 2);
    j += 1;
    if (j < 3) {
        goto loop_1;
    }
    i = 0;
    do {
        C[i] = reader(C, 3);
        i += 1;
    } while (i < 5);
    k = 0;
    while (k < 6) {
        A[k] = reader(A, 4);
        k += 1;
    }
}
'''


def of(label, source=SOURCE, name='f'):
    return [t for l, t in h.variants(source, name) if l == label]


def test_a_later_loop_of_a_shared_counter_gets_a_variable_of_its_own():
    texts = of(h.FRESH)
    second = [t for t in texts if 'i_b = 0;\n    do {\n        C[i_b]' in t]
    assert len(second) == 1
    assert '    s32 i;\n    s32 i_b;\n    s32 j;' in second[0]  # declared right after the shared one, same type
    assert 'i_b += 1;' in second[0] and '} while (i_b < 5);' in second[0]
    assert 'A[i] = reader' in second[0] and '} while (i < 4);' in second[0]  # the first loop keeps `i`
    assert not any('s32 j_b' in t or 's32 k_b' in t for t in texts)  # a counter of one loop has nothing to split


def test_a_loop_takes_another_counter_whose_own_loops_do_not_overlap_it():
    texts = of(h.REASSIGN)
    # the goto loop counts with `i` (whose do-while loops lie before and after it), and nothing else changes
    goto = [t for t in texts if '    i = 0;\nloop_1:\n    B[i] = reader(B, 2);\n    i += 1;\n    if (i < 3) {' in t]
    assert len(goto) == 1 and 's32 j;' in goto[0] and '    j = 0;' not in goto[0]
    # the second do-while goes to `k`, whose while loop comes after it, so the two do not overlap
    assert any('    k = 0;\n    do {\n        C[k] = reader' in t and '} while (k < 5);' in t for t in texts)
    for t in texts:
        assert t.count('s32 i;') == t.count('s32 j;') == t.count('s32 k;') == 1  # nothing declared or dropped


def test_two_counters_whose_loops_never_overlap_become_one_variable():
    texts = of(h.MERGE)
    assert len(texts) == 3  # i+j, i+k and j+k: every pair of the three
    into_i = [t for t in texts if '    s32 j;\n' not in t and '    s32 k;\n' in t]
    assert len(into_i) == 1
    assert 'B[i] = reader(B, 2);' in into_i[0] and '} while (i < 3)' not in into_i[0] and 'if (i < 3) {' in into_i[0]
    assert 'j' not in into_i[0].replace('reader', '').replace('loop_1', '')  # every mention renamed, declaration gone


def test_two_loops_trade_their_counters():
    swapped = [t for t in of(h.SWAP) if 'B[i] = reader(B, 2);' in t and 'A[j] = reader(A, 1);' in t]
    assert swapped
    assert '    j = 0;\n    do {\n        A[j]' in swapped[0] and '    i = 0;\nloop_1:\n    B[i]' in swapped[0]
    assert '} while (j < 4);' in swapped[0] and 'if (i < 3) {' in swapped[0]


def test_reuse_comes_before_fresh_splits_then_merges_and_swaps():
    labels = [l for l, _ in h.variants(SOURCE, 'f')]
    assert labels == sorted(labels, key=[h.REASSIGN, h.FRESH, h.MERGE, h.SWAP].index)


def test_a_counter_read_before_or_between_its_loops_is_left_alone():
    between = SOURCE.replace('    j = 0;\nloop_1:', '    A[0] = i;\n    j = 0;\nloop_1:')  # `i` read between its two loops
    assert 'i' not in h._counters(between, 'f')[0] and {'j', 'k'} <= set(h._counters(between, 'f')[0])
    texts = [t for _, t in h.variants(between, 'f')]
    assert texts and all('A[0] = i;' in t and '    s32 i;\n' in t and '        A[i] = reader(A, 1);' in t for t in texts)
    before = SOURCE.replace('    i = 0;\n    do {\n        A[i]', '    B[0] = k;\n    i = 0;\n    do {\n        A[i]', 1)
    assert 'k' not in h._counters(before, 'f')[0]
    only = PRELUDE + 'void g(void) {\n    s32 i;\n    i = 0;\n    do {\n        A[i] = 1;\n        i += 1;\n    } while (i < 4);\n    B[0] = i;\n}\n'
    assert h.variants(only, 'g') == []


def test_a_counter_read_after_its_last_loop_may_take_loops_but_not_give_its_own_up():
    text = SOURCE.replace('        k += 1;\n    }\n', '        k += 1;\n    }\n    A[0] = k;\n')
    found = h._counters(text, 'f')[0]
    assert {'i', 'j', 'k'} <= set(found) and found['k'][3] and not found['i'][3]
    texts = [t for _, t in h.variants(text, 'f')]
    assert texts and all('A[0] = k;' in t and '    k = 0;\n    while (k < 6) {' in t for t in texts)  # k keeps its loop
    # an earlier loop may count with `k`: k's own loop sets it again before the later read
    assert any('    k = 0;\n    do {\n        C[k] = reader' in t for t in texts)
    # `k` is never merged away or traded, which would hand its later reader another loop's value
    assert all('    s32 k;\n' in t for t in texts)


def test_a_later_loop_may_take_a_counter_whose_readers_all_come_before_it():
    # A 1133-instruction effect spawner: the first loop's counter is read after that loop (a table index) and a later
    # loop, below the read, counted with a variable of its own; taking the first loop's counter is safe (it sets it
    # again below the read) and the allocator then sees one pseudo for both loops: 6040 -> 6000.
    text = PRELUDE + '''
void f(void) {
    s32 i;
    s32 k;

    i = 0;
    do {
        A[i] = reader(A, 1);
        i += 1;
    } while (i < 4);
    A[9] = i;
    k = 0;
    do {
        B[k] = reader(B, 2);
        k += 1;
    } while (k < 5);
}
'''
    found = h._counters(text, 'f')[0]
    assert found['i'][3] and not found['k'][3]  # `i` is read after its loop
    texts = [t for _, t in h.variants(text, 'f')]
    # the second loop counts with `i`: it sets it below the read of the first loop's value
    assert any('    i = 0;\n    do {\n        B[i] = reader(B, 2);' in t and 'A[9] = i;' in t for t in texts)
    # a read below the second loop would see its value instead: no such child
    after = text.replace('    } while (k < 5);\n}', '    } while (k < 5);\n    A[8] = i;\n}')
    assert all('B[i] = reader' not in t for _, t in h.variants(after, 'f'))


# the loops of a function that reads a counter long after its goto loop: `a` counts the first loop, `b` the inner goto
# loop of the second, and `if (b)` guards the last loop's body (the same work in both arms)
GUARDED = PRELUDE + '''
void g(void) {
    s32 a;
    s32 b;
    s32 c;

    a = 0;
    do {
        A[a] = reader(A, 1);
        a += 1;
    } while (a < 3);
    c = 0;
    do {
        b = 0;
        A[c] = 0;
inner:
        B[b] = reader(B, 4);
        b += 1;
        if (b < 3) {
            goto inner;
        }
        c += 1;
    } while (c < 5);
    c = 0;
    do {
        if (b) {
            C[c] = reader(C, 1);
            c += 1;
        } else {
            C[c] = reader(C, 1);
            c += 1;
        }
    } while (c < 3);
}
'''


def test_a_loop_takes_a_counter_that_a_later_guard_reads_and_the_guard_still_reads_the_inner_loops_last_value():
    found = h._counters(GUARDED, 'g')[0]
    assert set(found) == {'a', 'b', 'c'} and found['b'][3] and not found['a'][3]  # the goto loop counts; `if (b)` reads
    taking = [t for t in of(h.REASSIGN, GUARDED, 'g') if '    b = 0;\n    do {\n        A[b] = reader(A, 1);' in t]
    assert len(taking) == 1  # the first loop counts with `b`, whose set in the second loop precedes the guard's read
    body = taking[0][taking[0].index('void g'):]
    assert 'if (b) {' in body and '    s32 a;\n' in body and not re.search(r'\ba\b', body.replace('    s32 a;\n', ''))
    # the loop after `b`'s last loop can't take `b`: the guard would read that loop's value, not the inner loop's
    assert not any('    b = 0;\n    do {\n        if (b) {' in t or 'C[b]' in t for _, t in h.variants(GUARDED, 'g'))
    # and `b`'s own inner loop is never given another counter (the guard would lose it) or merged or traded away
    labels = [(l, t) for l, t in h.variants(GUARDED, 'g')]
    assert all('B[b] = reader(B, 4);' in t and 'if (b) {' in t for l, t in labels)


def test_a_counter_whose_address_is_taken_is_left_alone():
    taken = SOURCE.replace('A[i] = reader(A, 1);', 'A[i] = reader(&i, 1);')
    assert 'i' not in h._counters(taken, 'f')[0]
    texts = [t for _, t in h.variants(taken, 'f')]
    assert texts and all('A[i] = reader(&i, 1);' in t and '    s32 i;\n' in t for t in texts)  # never renamed


def test_only_local_integers_of_one_type_are_counters_and_pair_up():
    pointer = PRELUDE + ('void g(void) {\n    u8 *p;\n    u8 *q;\n    p = 0;\n    do {\n        p += 1;\n    } while (p < B);\n'
                         '    q = 0;\n    do {\n        q += 1;\n    } while (q < C);\n}\n')
    assert h.variants(pointer, 'g') == []
    mixed = SOURCE.replace('    s32 j;\n', '    s16 j;\n', 1)
    texts = [t for _, t in h.variants(mixed, 'f')]
    assert texts and all('    s16 j;\n' in t and 'B[j] = reader(B, 2);' in t for t in texts)  # j neither takes nor gives


def test_a_counter_needs_a_plain_number_set_before_its_loop_and_a_step_and_a_test():
    for text in (SOURCE.replace('    j = 0;\nloop_1:', '    j = n;\nloop_1:'),  # set from a variable
                 SOURCE.replace('    j = 0;\nloop_1:', '    j = 0;\n    if (n) {\n        n = 1;\n    }\nloop_1:'),  # a branch between
                 SOURCE.replace('    j += 1;\n    if (j < 3)', '    n += 1;\n    if (j < 3)'),  # never stepped
                 SOURCE.replace('    if (j < 3) {', '    if (n < 3) {')):  # not tested
        regions = h._counters(text, 'f')[0]
        assert 'j' not in regions and {'i', 'k'} <= set(regions)


def test_a_loop_nested_in_another_loops_region_does_not_share_its_counter():
    nested = PRELUDE + ('void g(void) {\n    s32 i;\n    s32 j;\n    i = 0;\n    do {\n        j = 0;\n        do {\n'
                        '            A[j] = i;\n            j += 1;\n        } while (j < 2);\n        i += 1;\n    } while (i < 3);\n'
                        '    j = 0;\n    do {\n        B[j] = 1;\n        j += 1;\n    } while (j < 2);\n}\n')
    texts = [t for _, t in h.variants(nested, 'g')]
    assert texts
    # the inner loop's counter never becomes the outer loop's (it would be reset on every pass): no variant reads `A[x] = x`
    assert not any(re.search(r'A\[(\w+)\] = \1;', t) for t in texts)
    # and the two never merge into one variable, whichever pair of names is left
    assert not any(t.count('s32 ') < 4 and 'void g' in t and t.count('    s32 ') == 1 for t in texts)
    assert any('    j = 0;\n    do {\n        i = 0;' in t for t in texts)  # a swap keeps them distinct


def test_variants_are_distinct_bounded_and_never_the_source():
    texts = [t for _, t in h.variants(SOURCE, 'f')]
    assert texts and len(texts) == len(set(texts)) <= h.LIMIT and SOURCE not in texts


def test_nothing_for_a_missing_function_or_one_without_counter_loops():
    assert h.variants(SOURCE, 'missing') == []
    assert h.variants(PRELUDE + 'void g(void) {\n    s32 i;\n    i = 0;\n    A[0] = i;\n}\n', 'g') == []
    assert h.variants(SOURCE.replace('void f(s32 n) {', 'void f(s32 n) {\n    __asm__("nop");'), 'f') == []


def test_reuse_counter_across_adjacent_guarded_loops_with_prior_values():
    from decomprepair.loop_counter_roles_repairs import guarded_reuse_variants

    source = """
void f(void) {
    u32 first;
    u32 second;
    first = load();
    second = consume(first);
    publish(second);
    first = 0;
    ready();
    if (count1) {
        do {
            put(first);
            first += 1;
        } while (first < count1);
    }
    second = 0;
    if (count2) {
        do {
            put(second);
            second += 1;
        } while (second < count2);
    }
}
"""
    rows = [
        ('r', 'move $s1, $zero', 'move $a2, $zero'),
        ('r', 'addiu $s1, $s1, 1', 'addiu $a2, $a2, 1'),
        ('r', 'sltu $v0, $s1, $v0', 'sltu $v0, $a2, $v0'),
    ]
    [(family, candidate)] = guarded_reuse_variants(source, 'f', rows)
    assert family == 'guarded_loop_counter_reuse'
    assert 'second = consume(first);' in candidate
    assert 'second = 0;\n    ready();' in candidate
    assert 'while (second < count1);' in candidate
    assert not guarded_reuse_variants(source, 'f', rows[:-1])
    assert not guarded_reuse_variants(source.replace('second = 0;', 'publish(first); second = 0;'), 'f', rows)
    assert not guarded_reuse_variants(source.replace('ready();', 'publish(second);'), 'f', rows)
    assert not guarded_reuse_variants(source.replace('consume(first)', 'consume(&first)'), 'f', rows)


def test_a_counter_set_in_its_for_header_is_a_counter_loop():
    source = """void f(void) {
    s32 i;
    s32 j;
    for (i = 0; i < 4; i++) {
        A[i] = reader(A, 1);
    }
    for (j = 0; j < 4; j++) {
        B[j] = reader(B, 2);
    }
}
"""
    assert {'i', 'j'} <= set(h._counters(source, 'f')[0])
    assert any(label == h.MERGE for label, _ in h.variants(source, 'f'))
