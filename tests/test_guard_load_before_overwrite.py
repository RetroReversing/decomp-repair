from decomprepair import guard_load_before_overwrite, registry

SOURCE = """void update(Obj *o) {
    o->age++;
    o->age = 0;
    if (o->wait == 0) {
        o->state = 1;
    }
}
"""


def children(source):
    return guard_load_before_overwrite.variants(source, 'update')


def test_the_guard_is_read_before_the_overwriting_store():
    ((family, child),) = children(SOURCE)
    assert family == 'guard_load_before_overwrite'
    assert '    int guard_value0;\n' in child
    assert 'guard_value0 = (int) o->wait;\n    o->age = 0;\n    if (guard_value0 == 0) {' in child


def test_m2c_casted_base_and_written_increment():
    source = SOURCE.replace('o->age++;', '((R*)o)->age = (s32) (((R*)o)->age + 1);').replace(
        'o->age = 0;', '((R*)o)->age = 0;').replace('o->wait', '((R*)o)->wait')
    ((_, child),) = children(source)
    assert 'guard_value0 = (int) ((R*)o)->wait;' in child


def test_not_for_another_base_the_same_member_or_a_lone_store():
    assert not children(SOURCE.replace('o->wait', 'p->wait'))
    assert not children(SOURCE.replace('o->wait', 'o->age'))
    assert not children(SOURCE.replace('    o->age++;\n', ''))


def test_declared_to_the_registry():
    assert any(entry.module == 'guard_load_before_overwrite' for entry in registry.declared())
