from decomprepair.branch_layout_repairs import scalar_tails

SOURCE = '''
extern int shared_reset;
extern int state;
int f(int branch) {
    int index;
    if (branch) {
        state = 8;
        shared_reset = 0;
        index = 1;
    } else {
        state = 2;
        shared_reset = 0;
        index = 0;
    }
    return index;
}
'''


def test_sinks_shared_reset_past_independent_local_assignments():
    [(family, candidate)] = scalar_tails(SOURCE, 'f')
    assert family == 'common_scalar_tail'
    assert candidate.count('shared_reset = 0;') == 1
    assert candidate.index('shared_reset = 0;') > candidate.index('index = 0;')


def test_leaves_aliasing_or_control_flow_tails_alone():
    for source in (
        SOURCE.replace('index = 0;', 'state = 0;'),
        SOURCE.replace('index = 0;', 'return 0;'),
        SOURCE.replace('state = 2;', 'again: state = 2;'),
        SOURCE.replace('extern int shared_reset;', 'extern volatile int shared_reset;'),
        '#define shared_reset alias\n' + SOURCE,
    ):
        assert not scalar_tails(source, 'f')
