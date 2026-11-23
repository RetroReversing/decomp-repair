"""comma_gate_plain: m2c's comma-assignment gate as the plain condition, and a held volatile read used from its local."""
from decomprepair import comma_gate_plain as cg
from decomprepair import registry

GATE = '''s32 g(void *);

void f(void *arg0, u32 lim) {
    u32 held;
    u32 sum;
    s32 flag;

    sum = (*((volatile u32 *) (((char *) arg0) + 0x34))) + (*((u32 *) (((char *) arg0) + 0x38)));
    held = *((volatile u32 *) (((char *) arg0) + 0x38));
    if (((*((volatile u32 *) (((char *) arg0) + 0x38))) != 0) && (((flag = sum < lim, (*((u8 *) (((char *) arg0) + 1))) != 0)) || ((flag = sum < lim, (*((s32 *) (((char *) arg0) + 0x3C))) == 0))) && (flag == 0)) {
        g(arg0);
    }
}
'''


def children(source):
    return cg.variants(source, 'f')


def test_gate_becomes_the_plain_condition():
    plain = [text for family, text in children(GATE) if family == cg.FAMILY and 'flag' not in text]
    assert plain, 'no child dropped the flag'
    text = plain[0]
    assert '!(sum < lim)' in text
    assert text.count('sum < lim') == 1  # evaluated once, as the target does
    assert 's32 flag;' not in text


def test_volatile_local_is_read_from_the_local():
    rereads = [text for family, text in children(GATE) if family == cg.FAMILY_REREAD]
    assert rereads
    assert 'held != 0' in rereads[0].replace('((', '(')
    assert rereads[0].count('volatile') == 2  # the local's own read and the sum's


def test_both_edits_together_are_one_child():
    both = [text for _family, text in children(GATE) if 'flag' not in text and 'held != 0' in text.replace('((', '(')]
    assert both


def test_the_flag_read_elsewhere_blocks_the_rewrite():
    source = GATE.replace('        g(arg0);', '        g(arg0);\n        flag = 1;')
    assert not [text for family, text in children(source) if family == cg.FAMILY]


def test_a_call_in_the_compared_expression_blocks_the_rewrite():
    source = GATE.replace('flag = sum < lim', 'flag = g(arg0) < lim')
    assert not [text for family, text in children(source) if family == cg.FAMILY]


def test_a_different_expression_per_way_blocks_the_rewrite():
    source = GATE.replace('(flag = sum < lim, (*((s32 *)', '(flag = sum < lim + 1, (*((s32 *)')
    assert not [text for family, text in children(source) if family == cg.FAMILY]


def test_it_declares_itself_to_the_registry():
    repair = registry.get('comma_gate_plain')
    assert repair is not None and registry.problems(repair) == []


def test_held_read_follows_the_sum_that_reads_the_same_word():
    a = "    held = *((volatile u32 *) (((char *) arg0) + 0x38));\n"
    b = "    sum = (*((volatile u32 *) (((char *) arg0) + 0x34))) + (*((u32 *) (((char *) arg0) + 0x38)));\n"
    source = GATE.replace(b + a, a + b)
    moved = [text for family, text in children(source) if family == cg.FAMILY_REREAD]
    assert moved
    assert moved[0].index('sum =') < moved[0].index('held =')  # the target loads the sum's words, then the held one
