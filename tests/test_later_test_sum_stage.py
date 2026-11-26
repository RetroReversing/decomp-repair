"""A later test's `p->member + K` staged ahead of the test before it."""
from decomprepair import later_test_sum_stage as stage

SOURCE = '''typedef struct Node { struct Node *next; int start; float *ratio; } Node;
int f(Node *p, int addr, int end) {
    while (p) {
        if (addr < p->start)
            break;
        else if (end <= p->start + 0x400) {
            return 1;
        }
        p = p->next;
    }
    return 0;
}
'''


def children(source, header=''):
    return [text for family, text in stage.variants(source, 'f', header) if family == 'later_test_sum_stage']


def test_the_sum_is_computed_before_the_first_test():
    out = children(SOURCE)
    assert len(out) == 1
    assert 'int __stage_sum;' in out[0]
    assert out[0].index('__stage_sum = p->start + 0x400;') < out[0].index('if (addr < p->start)')
    assert 'else if (end <= __stage_sum)' in out[0]


def test_a_plain_second_if_after_a_return_works_too():
    source = SOURCE.replace('            break;\n        else if', '            return 2;\n        if')
    assert len(children(source)) == 1


def test_a_base_the_first_test_does_not_read_is_left_alone():
    assert not children(SOURCE.replace('if (addr < p->start)', 'if (addr < end)'))


def test_a_member_that_is_not_an_integer_is_left_alone():
    assert not children(SOURCE.replace('int start;', 'float start;'))
    assert not children(SOURCE.replace('int start;', 'char *start;'))


def test_a_first_test_that_falls_through_is_left_alone():
    assert not children(SOURCE.replace('            break;\n', '            addr = 0;\n'))
