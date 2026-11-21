"""Rewrites that decide which values a function's loops keep in saved registers."""
from decomprepair import block_register_repairs as blocks

SOURCE = '''extern s16 Totals;
extern s16 Scores;
extern s32 Count;
s32 slot(s32);
void *text(s32);
void put(void *, s32);

void f(s32 key) {
    s16 *totals;
    s16 *scores;
    s32 idx;
    void *buf;
    s32 i;

    memset(&Totals, 0, 4);
    memset(&Scores, 0, 0x16);
    scores = &Scores;
    totals = &Totals;
    i = 0;
    do {
        idx = slot(i) & 0xFFFF;
        totals[idx] += scores[idx];
        i += 1;
    } while (i < Count);
    i = 0;
    do {
        idx = slot(i) & 0xFFFF;
        buf = text(idx);
        put(buf, scores[idx]);
        i += 1;
    } while (i < 2);
    i = 0;
    do {
        idx = slot(i) & 0xFFFF;
        buf = text(idx + 1);
        put(buf, 2);
        i += 1;
    } while (i < 3);
    idx = slot(key);
    buf = text(idx);
    put(buf, scores[idx]);
}
'''


def families(source):
    return [family for family, _ in blocks.variants(source, 'f')]


def test_a_pointer_to_a_global_becomes_the_global_s_address():
    # N64 (KMC GCC 2.7.2): the draft's two table pointers were pseudos of their own; without them the first loop
    # matched (750 -> 470).
    (family, text), *_ = [v for v in blocks.variants(SOURCE, 'f') if v[0] == blocks.SYMBOL]
    assert 'scores' not in text and 'totals' not in text
    assert 'totals[idx] += scores[idx];' not in text
    assert '(&Totals)[idx] += (&Scores)[idx];' in text
    assert '    s16 *totals;' not in text and 'scores = &Scores;' not in text
    assert 'memset(&Totals, 0, 4);' in text


def test_a_pointer_that_is_written_again_or_has_its_own_address_taken_stays():
    again = SOURCE.replace('    i = 0;\n    do {\n        idx = slot(i) & 0xFFFF;\n        totals[idx]',
                           '    totals = &Scores;\n    i = 0;\n    do {\n        idx = slot(i) & 0xFFFF;\n        totals[idx]', 1)
    assert not any('totals' not in t for f, t in blocks.variants(again, 'f') if f == blocks.SYMBOL and '(&Totals)' in t)
    escaped = SOURCE.replace('put(buf, scores[idx]);\n        i += 1;', 'put(&scores, scores[idx]);\n        i += 1;', 1)
    assert 'put(&scores' in escaped
    assert not any('(&Scores)' in t for f, t in blocks.variants(escaped, 'f') if f == blocks.SYMBOL)


def test_a_temporary_each_loop_sets_first_gets_one_name_per_loop():
    # N64: the slot index and a text buffer shared by four loops were one pseudo, so one saved register (470 -> 280).
    texts = [t for f, t in blocks.variants(SOURCE, 'f') if f == blocks.SPLIT]
    assert any('buf_b = text(idx);' in t and 'put(buf_b, scores[idx]);' in t and '    void * buf_b;' in t for t in texts)
    assert any('idx_b = slot(i) & 0xFFFF;' in t and '    s32 idx_b;' in t for t in texts)
    # the first loop and the straight-line tail keep the original name
    assert any('idx = slot(i) & 0xFFFF;\n        totals[idx] += scores[idx];' in t and 'idx = slot(key);' in t for t in texts)


def test_a_temporary_read_before_it_is_set_in_a_loop_is_not_split():
    carried = SOURCE.replace('        idx = slot(i) & 0xFFFF;\n        buf = text(idx);',
                             '        put(buf, 1);\n        idx = slot(i) & 0xFFFF;\n        buf = text(idx);')
    assert not any('buf_' in t for f, t in blocks.variants(carried, 'f') if f == blocks.SPLIT)


def test_a_do_while_counter_loop_becomes_a_for():
    # N64: the test is made at the loop head instead of being copied before it (1130 -> 770).
    texts = [t for f, t in blocks.variants(SOURCE, 'f') if f == blocks.FOR]
    assert any('for (i = 0; i < 2; i++) {\n        idx = slot(i) & 0xFFFF;\n        buf = text(idx);\n'
               '        put(buf, scores[idx]);\n    }\n' in t for t in texts)
    assert all('i += 1;' not in t.split('for (i = 0; i < 2')[1].split('}')[0] for t in texts if 'for (i = 0; i < 2' in t)
    withcontinue = SOURCE.replace('put(buf, scores[idx]);\n        i += 1;', 'if (idx) continue;\n        put(buf, scores[idx]);\n        i += 1;')
    assert not any('for (i = 0; i < 2' in t for f, t in blocks.variants(withcontinue, 'f') if f == blocks.FOR)


def test_the_counter_init_can_stay_a_statement_of_its_own():
    # N64: the init before the loop's pointer declaration, not in the for header, moved a `move $s4, $zero` to
    # where the target has it (80 -> 20).
    source = ('void f(void) {\n    s32 i;\n\n    i = 0;\n    {\n        volatile u8 *mode = (u8 *)&G;\n'
              '        do {\n            use(mode[0]);\n            i += 1;\n        } while (i < 2);\n    }\n}\n')
    texts = [t for f, t in blocks.variants(source, 'f') if f == blocks.FOR]
    assert any('i = 0;\n    {\n        volatile u8 *mode = (u8 *)&G;\n        for (; i < 2; i++) {\n            use(mode[0]);\n        }\n' in t
               for t in texts)
    assert any('for (i = 0; i < 2; i++) {' in t for t in texts)


def test_nothing_to_offer_without_loops_or_pointers():
    assert not blocks.variants('void g(void) { h(); }\n', 'g')
    assert not families('void g(void) { asm("nop"); }\n')


def test_a_nonzero_test_can_go_through_an_inline_helper():
    # N64: after `beqz v`, CSE replaced `v` on the else path by the counter register that also held zero
    # (`slt $v0, $s4, $v0`); through an inline helper the byte kept its own register (20 -> 0).
    source = ('s32 n;\nvoid f(void) {\n    s32 mode;\n\n    mode = G;\n    if (mode != 0) {\n        a();\n    } else if (mode < n) {\n'
              '        b();\n    }\n    if (n != 0) {\n        c();\n    }\n}\n')
    texts = [t for fam, t in blocks.variants(source, 'f') if fam == blocks.NONZERO]
    helper = 'static inline int repair_nonzero(int value) { return value != 0; }\n'
    assert texts[0].startswith('s32 n;\n' + helper + 'void f(void) {')
    assert 'if (repair_nonzero(mode)) {' in texts[0] and 'if (repair_nonzero(n)) {' in texts[0]
    assert any('if (repair_nonzero(mode)) {' in t and 'if (n != 0) {' in t for t in texts)
    assert not any(blocks.NONZERO == fam for fam, _ in blocks.variants(texts[0], 'f'))
