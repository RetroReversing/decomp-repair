from decomprepair import registry
from decomprepair import scaled_offset_local as repair

SOURCE = '''void f(char *p, s16 kind)
{
    s32 t;
    if (kind != 0)
    {
        sprintf(buf, fmt, ((s8 *)p)[idx(kind) * 8 + 0x1FF], t);
        t = lookup(*(u16 *)(q + ((u8 *)p)[kind * 8 + 0x1FD] * 2 + 0x2C));
    }
}
'''


def texts(source=SOURCE):
    return [t for _, t in repair.variants(source, 'f')]


def test_the_product_is_computed_into_a_local_on_the_line_before():
    found = texts()
    both = next(t for t in found if 'off2' in t)
    assert 'off1 = idx(kind) * 8;\n        sprintf(buf, fmt, *(s8 *)((char *)p + off1 + 0x1FF), t);' in both
    assert 'off2 = kind * 8;\n        t = lookup(*(u16 *)(q + *(u8 *)((char *)p + off2 + 0x1FD) * 2 + 0x2C));' in both
    assert 's32 off1;' in both and 's32 off2;' in both


def test_each_site_is_offered_alone_too():
    found = texts()
    assert len(found) == 3
    assert sum('off2' in t for t in found) == 1


def test_a_sum_spelling_is_read_as_well():
    source = SOURCE.replace('((s8 *)p)[idx(kind) * 8 + 0x1FF]', '*(s16 *)((char *)p + (kind * 8) + 0x1FF)')
    assert any('*(s16 *)((char *)p + off1 + 0x1FF)' in t for t in texts(source))


def test_a_call_that_is_not_the_first_of_its_statement_is_left_alone():
    source = SOURCE.replace('sprintf(buf, fmt, ', 'sprintf(buf, g(1), ')
    assert not any('off1 = idx' in t for t in texts(source))


def test_a_loop_head_is_left_alone():
    source = SOURCE.replace('        sprintf(buf, fmt, ((s8 *)p)[idx(kind) * 8 + 0x1FF], t);', '        while (((s8 *)p)[kind * 8 + 0x1FF] > 0)\n        {\n            h();\n        }')
    assert not any('off1 = kind * 8;\n        while' in t for t in texts(source))


def test_it_is_declared_for_every_lane():
    declared = registry.get('scaled_offset_local')
    assert declared is not None and registry.problems(declared) == []
    assert registry.run('scaled_offset_local', source=SOURCE, name='f')


def test_the_offset_is_also_offered_above_the_array_pointer_lines_of_the_same_statement():
    source = SOURCE.replace('        sprintf(buf, fmt, ((s8 *)p)[idx(kind) * 8 + 0x1FF], t);',
                            '        field1 = (s16 *)((char *)p + 0x1BC);\n        sprintf(buf, fmt, ((s8 *)p)[idx(kind) * 8 + 0x1FF], field1[kind]);')
    found = texts(source)
    assert any("        off1 = idx(kind) * 8;\n        field1 = (s16 *)((char *)p + 0x1BC);\n        sprintf" in t for t in found)
    assert any('field1 = (s16 *)((char *)p + 0x1BC);\n        off1 = idx(kind) * 8;' in t for t in found)


def test_a_member_of_a_variable_is_a_base_too():
    source = SOURCE.replace('((s8 *)p)[idx(kind) * 8 + 0x1FF]', '((s8 *)store.pointer)[idx(kind) * 8 + 0x1FF]')
    assert any('*(s8 *)((char *)store.pointer + off1 + 0x1FF)' in t for t in texts(source))
