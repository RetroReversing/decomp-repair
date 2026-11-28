"""zero_running_max on a made-up score picker in m2c's shape (no game's code)."""
from decomprepair.registry import declared
from decomprepair.zero_running_max import FAMILY, variants

DRAFT = '''extern u32 scores[];
extern s32 on;

s32 pick(void) {
    u32 var_a0;
    u32 var_a0_2;

    var_a0 = 0;
    if ((on != 0) && ((u32) M2C_FIELD(scores, u32 *, 0) > 0U)) {
        var_a0 = M2C_FIELD(scores, u32 *, 0);
    }
    use(var_a0);
    var_a0_2 = 0;
    if (scores[1] > 0U) {
        var_a0_2 = scores[1];
    }
    return var_a0_2;
}
'''


def test_every_first_candidate_is_compared_with_the_maximum():
    [(family, child)] = variants(DRAFT, 'pick')
    assert family == FAMILY
    assert '(u32) M2C_FIELD(scores, u32 *, 0) > (u32) var_a0)' in child
    assert 'if (scores[1] > (u32) var_a0_2) {' in child


def test_a_maximum_that_changed_since_zero_keeps_the_constant():
    source = DRAFT.replace('    var_a0_2 = 0;\n', '    var_a0_2 = 0;\n    var_a0_2 = on;\n')
    [(_, child)] = variants(source, 'pick')
    assert 'if (scores[1] > 0U) {' in child


def test_a_block_that_stores_something_else_is_left_alone():
    assert variants(DRAFT.replace('var_a0 = M2C_FIELD(scores, u32 *, 0);', 'var_a0 = 1;')
                    .replace('var_a0_2 = scores[1];', 'var_a0_2 = 2;'), 'pick') == []


def test_it_is_registered():
    assert any(FAMILY in repair.families for repair in declared())


FAR = '''s32 pick(s32 c) {
    s32 leader;
    u32 best;

    leader = 0;
    if (c != 0) {
        if (flag == 0) {
            return 0;
        }
        goto join;
    }
join:
    best = 0;
    if (scores[1] > 0U) {
        best = scores[1];
    }
    return leader + best;
}
'''


def test_the_other_zero_is_moved_next_to_the_maximum():
    [(_, both), (_, compare)] = variants(FAR, 'pick')
    assert 'join:\n    leader = 0;\n    best = 0;\n    if (scores[1] > (u32) best) {' in both
    assert both.count('leader = 0;') == 1
    assert 'u32 best;\n\n    leader = 0;\n    if (c != 0)' in compare


def test_a_zero_read_in_between_stays_where_it_is():
    [(_, child)] = variants(FAR.replace('return 0;', 'return leader;'), 'pick')
    assert 'u32 best;\n\n    leader = 0;\n    if (c != 0)' in child


def test_a_goto_leaving_the_span_stops_the_move():
    assert len(variants(FAR.replace('goto join;', 'goto out;').replace('return leader + best;', 'out:\n    return leader + best;'), 'pick')) == 1
