"""The constants a loop stores to one field, written through one local (an N64 billboard-strip builder, 2535 -> 1930)."""
from decomprepair import registry
from decomprepair.store_constant_web import FAMILY, variants

SOURCE = """typedef struct { s16 ob[3]; u16 flag; s16 tc[2]; u8 cn[4]; } Vtx;
extern Vtx verts[];
s32 strip(s32 count, s32 base)
{
    s32 i;
    s32 k;
    Vtx *v;

    for (i = k = 0; i < count; i++) {
        v = &verts[k++ + base];
        v->cn[0] = 0xFF;
        v->cn[3] = 0;
        v = &verts[k++ + base];
        v->cn[0] = 0xFF;
        v->cn[3] = 0x80;
        v = &verts[k++ + base];
        v->cn[0] = 0xFF;
        v->cn[3] = 0;
    }
    return k;
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'strip', '') if family == FAMILY]


def test_the_stores_from_the_first_non_zero_one_go_through_one_local():
    texts = children()
    assert any('        v->cn[3] = 0;\n        v = &verts[k++ + base];\n        v->cn[0] = 0xFF;\n'
               '        value = 0x80;\n        v->cn[3] = value;\n' in t
               and '        value = 0;\n        v->cn[3] = value;\n    }' in t
               and '    s32 value;\n' in t for t in texts), texts


def test_every_store_of_the_field_is_also_offered():
    assert any(t.count('v->cn[3] = value;') == 3 for t in children())


def test_a_field_stored_one_value_only_is_left_alone():
    assert not any('v->cn[0] = value' in t for t in children())


def test_a_store_outside_a_loop_is_left_alone():
    source = SOURCE.replace('    for (i = k = 0; i < count; i++) {\n', '    {\n')
    assert children(source) == []


def test_registered():
    assert any(FAMILY in repair.families for repair in registry.declared())
