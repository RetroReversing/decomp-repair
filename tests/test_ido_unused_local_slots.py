"""An IDO bit-stream reader: three steps the permuter could not take, each found by hand.

The reader kept one flag in its own local and the loop counter in another; the target's flag sat in the register the
draft gave to a constant, its frame was a word bigger than the draft's (a local nothing reads), and its saved registers
sat in the order of a different declaration order. Each step is a proposal here; the app's judge decides (the chain
from the draft's 89 to 0 was measured with ido-7.1 -O2 -mips2).
"""
from decomprepair import frame_padding_repairs, integer_lifetime_repairs, stack_repairs

DRAFT = '''s32 f(Reader *p, void *arg1) {
    s16 spE8[8];
    s16 sp60[4][13];
    s32 pos;
    u32 w;
    s32 avail;
    s32 flag;
    s32 i;

    pos = p->pos;
    avail = 32;
    w = 0;
    GETBITS(flag, 1);
    if (flag != 0) {
        avail = 0;
    }
    for (i = 0; i < 4; i++) {
        GETBITS(sp60[i][0], 3);
    }
    p->pos = pos - avail + w;
    return 0;
}
'''
NAME = 'f'


def merges(source=DRAFT):
    return [text for family, text in integer_lifetime_repairs.counter_reuse_variants(source, NAME)]


def test_a_flag_dead_before_a_loop_takes_the_loops_counter_and_keeps_its_declaration():
    (text,) = merges()
    assert 'GETBITS(i, 1);' in text and 'if (i != 0)' in text
    assert 's32 flag;' in text and text.count('flag') == 1  # the declaration stays: IDO still reserves its word
    assert ('merge_integer_lifetimes', text) in integer_lifetime_repairs.variants(DRAFT, NAME)


def test_the_counters_old_value_must_never_be_read():
    assert merges(DRAFT.replace('for (i = 0; i < 4; i++)', 'for (; i < 4; i++)')) == []
    assert merges(DRAFT.replace('    GETBITS(flag, 1);\n', '    GETBITS(flag, 1);\n    avail += i;\n')) == []


def test_a_flag_used_inside_or_after_the_loop_stays():
    assert merges(DRAFT.replace('        GETBITS(sp60[i][0], 3);', '        GETBITS(sp60[i][0], 3);\n        w = flag;')) == []
    assert merges(DRAFT.replace('    p->pos = pos', '    pos += flag;\n    p->pos = pos')) == []
    assert merges(DRAFT.replace('s32 flag;', 'short flag;')) == []


def test_one_word_of_frame_is_declared_at_each_gap_after_the_arrays_first():
    out = frame_padding_repairs.positioned_variants(DRAFT, NAME, 4)
    first = out[0][1]
    assert first.index('s16 sp60[4][13];') < first.index('__repair_unused_frame_0') < first.index('s32 pos;')
    assert {family for family, _ in out} == {frame_padding_repairs.POSITIONED_FAMILY}
    assert len({text for _, text in out}) == len(out) and all(text.count('__repair_unused_frame_') == 1 for _, text in out[:7])
    words = frame_padding_repairs.positioned_variants(DRAFT, NAME, 8)
    assert any(text.count('s32 __repair_unused_frame_') == 2 for _, text in words)


def test_only_a_whole_word_frame_difference_below_a_cap_and_no_scratch_already():
    for delta in (0, 2, 6, 36, -4):
        assert frame_padding_repairs.positioned_variants(DRAFT, NAME, delta) == []
    assert frame_padding_repairs.positioned_variants(DRAFT.replace('s32 pos;', 'volatile s32 pos;'), NAME, 4) == []
    assert frame_padding_repairs.positioned_variants('void g(void) {\n    g();\n}\n', 'g', 4) == []


def test_scalar_locals_are_reordered_past_what_one_swap_reaches_and_arrays_stay():
    merged = merges()[0]  # the flag is unused now: the used scalars are pos, w, avail, i
    moves = stack_repairs.declaration_moves(merged, NAME)
    out = [text for _, text in moves]
    wanted = ('s32 avail;', 'u32 w;', 's32 pos;')
    assert any(tuple(line.strip() for line in text.splitlines()[3:6]) == wanted for text in out)
    assert len(out) == 23  # all orders of four
    assert all(text.splitlines()[1:3] == ['    s16 spE8[8];', '    s16 sp60[4][13];'] for text in out)
    assert {family for family, _ in moves} == {'local_declaration_order'}
    assert merged not in out and len(out) == len(set(out))
    assert len(stack_repairs.declaration_moves(DRAFT, NAME)) == 9  # five used scalars: the reversal and the moves


def test_an_unused_local_keeps_its_place_while_the_used_ones_move():
    unused = DRAFT.replace('    s32 pos;\n', '    s32 pos;\n    s32 spare;\n')
    for _, text in stack_repairs.declaration_moves(unused, NAME):
        lines = [line.strip() for line in text.splitlines()]
        assert lines.index('s32 spare;') == [line.strip() for line in unused.splitlines()].index('s32 spare;')


def test_the_variants_reach_stack_repairs_when_the_function_leads_with_arrays():
    families = [family for family, _ in stack_repairs.variants(DRAFT, NAME)]
    assert 'local_declaration_order' in families


def test_a_short_run_has_nothing_to_reorder():
    assert stack_repairs.declaration_moves('void g(void) {\n    s16 a[2];\n    s32 x;\n    s32 y;\n    g();\n}\n', 'g') == []
