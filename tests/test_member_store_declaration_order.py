"""Member stores to one record written in the record's declaration order (an N64 drop-shadow renderer, 1020 -> 0)."""
from decomprepair.member_store_declaration_order import FAMILY, variants

SOURCE = '''typedef struct { s16 ob[3]; u16 flag; s16 tc[2]; u8 cn[4]; } Vtx;
extern Vtx gVerts[][30];
void g(s16 *src, f32 *u, s32 b) {
    s32 k;

    for (k = 0; k < 3; k++) {
        gVerts[b][k].ob[0] = src[0];
        gVerts[b][k].ob[1] = src[1];
        gVerts[b][k].flag = 0;
        gVerts[b][k].ob[2] = src[2];
        gVerts[b][k].tc[0] = u[k] * 32.0f;
        gVerts[b][k].cn[0] = 0;
        gVerts[b][k].tc[1] = u[k] * 16.0f;
        gVerts[b][k].cn[1] = 0;
    }
}
'''

ORDERED = '''        gVerts[b][k].ob[0] = src[0];
        gVerts[b][k].ob[1] = src[1];
        gVerts[b][k].ob[2] = src[2];
        gVerts[b][k].flag = 0;
        gVerts[b][k].tc[0] = u[k] * 32.0f;
        gVerts[b][k].tc[1] = u[k] * 16.0f;
        gVerts[b][k].cn[0] = 0;
        gVerts[b][k].cn[1] = 0;
'''


def test_the_run_follows_the_declaration():
    (family, text), = variants(SOURCE, 'g')
    assert family == FAMILY
    assert ORDERED in text
    run = SOURCE[SOURCE.index('        gVerts[b][k].ob[0]'):SOURCE.index('    }\n}')]
    assert text.replace(ORDERED, '') == SOURCE.replace(run, '')


def test_a_run_in_order_or_with_dependent_values_is_left_alone():
    assert variants(SOURCE.replace(SOURCE[SOURCE.index('        gVerts[b][k].ob[0]'):SOURCE.index('    }\n}')], ORDERED),
                    'g') == []
    assert variants(SOURCE.replace('.cn[0] = 0;', '.cn[0] = gVerts[b][k].flag;'), 'g') == []
    assert variants(SOURCE.replace('.cn[0] = 0;', '.cn[0] = next();'), 'g') == []
    assert variants(SOURCE.replace('.cn[0] = 0;', '.cn[0] = k++;'), 'g') == []


def test_members_no_single_struct_declares_are_left_alone():
    assert variants(SOURCE.replace('u8 cn[4]; } Vtx;', 'u8 cn[4]; } Vtx;\ntypedef struct { s16 ob[3]; u16 flag; } Two;')
                    .replace('gVerts[b][k].tc[0] = u[k] * 32.0f;\n', '').replace('gVerts[b][k].tc[1] = u[k] * 16.0f;\n', '')
                    .replace('gVerts[b][k].cn[0] = 0;\n', '').replace('gVerts[b][k].cn[1] = 0;\n', ''), 'g') == []
