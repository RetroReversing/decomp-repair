from decomprepair import field_array_base_local as repair
from decomprepair import registry

SOURCE = '''void f(char *p, u8 kind, s32 n)
{
    s32 t;
    if (n != 0)
    {
        t = g(n);
        sprintf(buf, fmt, *(s16 *)((char *)p + (kind * 2) + 0x1BC), t);
    }
}
'''


def texts(source=SOURCE):
    return [t for _, t in repair.variants(source, 'f')]


def test_the_array_s_address_is_a_local_and_the_index_is_applied_to_it():
    found = texts()
    assert len(found) == 1
    assert 'field1 = (s16 *)((char *)p + 0x1BC);\n        sprintf(buf, fmt, field1[kind], t);' in found[0]
    assert 's16 *field1;' in found[0]


def test_the_index_may_come_first_or_the_offset_in_the_middle():
    first = texts(SOURCE.replace('(char *)p + (kind * 2) + 0x1BC', '(kind * 2) + (char *)p + 0x1BC'))
    middle = texts(SOURCE.replace('(char *)p + (kind * 2) + 0x1BC', '(char *)p + 0x1BC + (kind * 2)'))
    assert 'field1[kind]' in first[0] and 'field1[kind]' in middle[0]


def test_two_sites_are_offered_together_and_alone():
    source = SOURCE.replace('t);\n', 't, *(u16 *)((char *)p + (n * 2) + 0x20));\n')
    found = texts(source)
    assert len(found) == 3 and sum('field2[n]' in t and 'field1[kind]' in t for t in found) == 1


def test_a_scale_that_is_not_the_element_size_or_a_base_that_changes_is_left_alone():
    assert not texts(SOURCE.replace('kind * 2', 'kind * 3'))
    assert not texts(SOURCE.replace('(char *)p + (kind * 2) + 0x1BC', '(char *)p++ + (kind * 2) + 0x1BC'))


def test_a_loop_head_is_left_alone():
    source = SOURCE.replace('        sprintf(buf, fmt, *(s16 *)((char *)p + (kind * 2) + 0x1BC), t);', '        while (*(s16 *)((char *)p + (kind * 2) + 0x1BC) > 0)\n        {\n            h();\n        }')
    assert not texts(source)


def test_it_is_declared_for_every_lane():
    declared = registry.get('field_array_base_local')
    assert declared is not None and registry.problems(declared) == []
    assert registry.run('field_array_base_local', source=SOURCE, name='f')


def test_a_member_of_a_variable_is_a_base_too():
    source = SOURCE.replace('(char *)p + (kind * 2) + 0x1BC', '(char *)store.pointer + (kind * 2) + 0x1BC')
    found = texts(source)
    assert found and 'field1 = (s16 *)((char *)store.pointer + 0x1BC);' in found[0]
