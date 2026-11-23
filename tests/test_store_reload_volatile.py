from decomprepair import registry
from decomprepair.store_reload_volatile import FAMILY, REPAIR, variants

SOURCE = """void start(Entity *e, void *arg0) {
    void *rec;
    ((Rec *) e)->value = arg0;
    rec = ((Rec *) e)->value;
    walk(rec);
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'start') if f == FAMILY]


def test_the_read_back_goes_through_a_volatile_lvalue():
    got = children()
    assert len(got) == 1
    assert 'rec = *(volatile __typeof__ (((Rec *) e)->value) *) &(((Rec *) e)->value);' in got[0]
    assert '((Rec *) e)->value = arg0;' in got[0]


def test_a_read_of_another_field_is_left_alone():
    assert children(SOURCE.replace('rec = ((Rec *) e)->value;', 'rec = ((Rec *) e)->other;')) == []


def test_a_read_that_is_not_the_next_statement_is_left_alone():
    assert children(SOURCE.replace('    rec = ', '    use(arg0);\n    rec = ')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
