"""A pointer local set once to a global array's element and read only for members, written as the indexed element."""
from decomprepair import element_pointer_direct_index as direct

SOURCE = '''typedef struct { s32 kind; f32 t; void *obj; } Rec;
extern Rec gRecs[];
extern s32 gCount;
void f(void *obj, f32 t, s32 flags) {
    Rec *ent;
    s32 i;

    for (i = 0; i < 4; i++) {
        if (flags & 1) {
            ent = &gRecs[gCount];
            ent->kind = 1;
            ent->t = t;
            ent->obj = obj;
        }
        gCount++;
    }
}
'''


def test_member_stores_are_written_through_the_element():
    (family, text), = direct.variants(SOURCE, 'f')
    assert family == direct.FAMILY
    assert 'ent' not in text
    assert ('            gRecs[gCount].kind = 1;\n            gRecs[gCount].t = t;\n'
            '            gRecs[gCount].obj = obj;\n') in text
    assert '    s32 i;' in text and 'gCount++;' in text


def test_a_call_or_index_change_in_between_keeps_the_pointer():
    called = SOURCE.replace('ent->t = t;', 'ent->t = g(t);')
    assert direct.variants(called, 'f') == []
    stepped = SOURCE.replace('ent->t = t;', 'gCount++;\n            ent->t = t;')
    assert direct.variants(stepped, 'f') == []


def test_a_pointer_used_otherwise_or_after_its_block_is_left_alone():
    passed = SOURCE.replace('ent->obj = obj;', 'ent->obj = ent;')
    assert direct.variants(passed, 'f') == []
    later = SOURCE.replace('        gCount++;\n', '        gCount++;\n        ent->kind = 2;\n')
    assert direct.variants(later, 'f') == []
    twice = SOURCE.replace('    Rec *ent;\n', '    Rec *ent;\n\n    ent = &gRecs[0];\n')
    assert direct.variants(twice, 'f') == []


def test_the_declaration_stays_when_it_shares_a_line():
    shared = SOURCE.replace('    Rec *ent;\n', '    Rec *ent; Rec *other;\n')
    (_, text), = direct.variants(shared, 'f')
    assert 'Rec *ent; Rec *other;' in text and 'gRecs[gCount].kind = 1;' in text
