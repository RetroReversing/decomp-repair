"""A member store moved above the loads of other members before it (a scroll window, 1380 -> 985)."""
from decomprepair.member_store_hoist import FAMILY, variants

SOURCE = """void update(Window *w)
{
    s32 delta, bound, old, pos;
    s16 i;

    delta = (w->scroll - old) * w->scale;
    i = 0;
    pos = 0;
    old = w->scroll * w->scale;
    bound = w->count;
    w->offset += delta;
    if (bound) {
        use(w);
    }
}
"""


def children(source):
    return [text for family, text in variants(source, 'update') if family == FAMILY]


def test_the_store_slides_up_past_one_to_four_independent_statements():
    found = children(SOURCE)
    assert len(found) == 4
    two = [t for t in found if t.index('w->offset += delta;') < t.index('old = w->scroll * w->scale;')
           and t.index('w->offset += delta;') > t.index('pos = 0;')]
    assert len(two) == 1
    assert '    w->offset += delta;\n    old = w->scroll * w->scale;\n    bound = w->count;\n    if (bound) {' in two[0]
    # the statement that computes the value it stores is never passed
    assert all(t.index('delta = (w->scroll') < t.index('w->offset += delta;') for t in found)


def test_a_statement_that_reads_the_stored_member_stops_the_slide():
    source = SOURCE.replace('bound = w->count;', 'bound = w->offset;')
    assert not any(t.index('w->offset += delta;') < t.index('bound = w->offset;') for t in children(source))


def test_a_call_between_stops_the_slide():
    source = SOURCE.replace('    pos = 0;\n', '    pos = lookup(w);\n')
    found = children(source)
    assert found and all(t.index('w->offset += delta;') > t.index('pos = lookup(w);') for t in found)


def test_a_member_of_the_same_name_through_another_pointer_stops_it():
    source = SOURCE.replace('bound = w->count;', 'bound = other->offset;')
    assert not any(t.index('w->offset += delta;') < t.index('bound = other->offset;') for t in children(source))


def test_a_store_that_is_the_first_statement_has_nothing_to_pass():
    source = SOURCE.replace('    delta = (w->scroll - old) * w->scale;\n', '').replace('    i = 0;\n    pos = 0;\n', '')
    assert children(source) != [] and all('w->offset += delta;' in t for t in children(source))
