"""A run of lookups through one index table, with every slot's address taken before the first load."""
from decomprepair import index_slot_addresses_first as m
from decomprepair import registry

SOURCE = '''void f(Vtx *verts, s32 *table, s32 i0, s32 i1, s32 i2) {
    Vtx *a;
    Vtx *b;
    Vtx *c;
    s32 *other;

    a = &verts[table[i0]];
    b = &verts[table[i1]];
    c = &verts[table[i2]];
    g(a, b, c);
    a = &verts[table[i2]];
    b = &verts[table[i1]];
    g(a, b, c);
}
'''


def test_addresses_come_first_one_run_or_all():
    out = m.variants(SOURCE, 'f')
    assert [family for family, _ in out] == ['index_slot_addresses_first'] * 3
    every, first, second = (text for _, text in out)
    assert ('    slot0 = &table[i0];\n    slot1 = &table[i1];\n    slot2 = &table[i2];\n'
            '    a = &verts[*slot0];\n    b = &verts[*slot1];\n    c = &verts[*slot2];\n') in first
    assert 's32 *slot0, *slot1, *slot2;' in first and '&table[i2]];' not in first
    assert 'a = &verts[table[i2]];' in first and 'a = &verts[table[i0]];' in second
    assert every.count('slot') == 5 * 3 and 'verts[table[' not in every
    assert every.count('{') == every.count('}')


def test_declines_what_would_change_the_reads():
    body = '    a = &verts[table[i0]];\n    b = &verts[table[i1]];\n'
    head = 'void f(Vtx *verts, s32 *table, s32 i0, s32 i1) {\n    Vtx *a;\n    Vtx *b;\n\n'
    assert m.variants(head + body + '}\n', 'f')
    for changed in (head + body.replace('b = &verts[table[i1]]', 'b = &verts[table[g()]]') + '}\n',
                    head + body.replace('a = ', 'i1 = ') + '}\n',
                    head + body.replace('    b = &verts[table[i1]];\n', '') + '}\n',
                    head + body.replace('    b =', '    g();\n    b =') + '}\n',
                    head.replace('    Vtx *a;\n', '') + body + '}\n'):  # `a` is not a local: it might be the table
        assert m.variants(changed, 'f') == [], changed


def test_registered():
    assert any(r.module == 'index_slot_addresses_first' for r in registry.declared())
