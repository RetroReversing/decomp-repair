"""A store before a branch goes into both ways out; the leave block's stores trade places."""
from decomprepair import arm_store_sink as a

SOURCE = '''extern struct Node *gHead;
extern struct Node *gOther;

void f(struct Node *entry) {
    struct Node *cur;
    struct Node *prev;

    prev = NULL;
    cur = gHead;
    if (cur == NULL) {
        gHead = entry;
        entry->next = NULL;
        continue;
    }
    do {
        if (entry->depth < cur->depth) {
            entry->next = cur;
            if (prev == NULL) {
                gHead = entry;
                goto next;
            }
            prev->next = entry;
            goto next;
        }
        prev = cur;
        cur = prev->next;
    } while (cur != NULL);
    prev->next = entry;
    entry->next = NULL;
next:;
}
'''
SUNK = '''            if (prev == NULL) {
                entry->next = cur;
                gHead = entry;
                goto next;
            }
            entry->next = cur;
            prev->next = entry;
            goto next;
'''
SWAPPED = '''        entry->next = NULL;
        gHead = entry;
        continue;
'''


def by_family():
    return dict(a.variants(SOURCE, 'f'))


def test_the_store_goes_into_both_ways_out():
    text = by_family()['arm_store_sink']
    assert SUNK in text
    assert '            entry->next = cur;\n            if (prev == NULL)' not in text
    assert SWAPPED not in text


def test_the_leave_blocks_stores_trade_places():
    text = by_family()['leave_store_swap']
    assert SWAPPED in text and SUNK not in text


def test_both_changes_come_in_one_child():
    text = by_family()['arm_store_sink_swap']
    assert SUNK in text and SWAPPED in text


def test_a_condition_that_reads_through_a_pointer_or_calls_is_left_alone():
    for cond in ('prev->next == NULL', 'check(prev)', 'prev[0] == NULL', 'entry == prev'):
        text = SOURCE.replace('prev == NULL', cond)
        assert 'arm_store_sink' not in dict(a.variants(text, 'f')), cond


def test_a_branch_whose_way_out_does_not_leave_is_left_alone():
    text = SOURCE.replace('            prev->next = entry;\n            goto next;\n        }', '            prev->next = entry;\n        }')
    assert 'arm_store_sink' not in dict(a.variants(text, 'f'))
    assert a.variants('void f(void) { int a; a = 1; }', 'f') == []
