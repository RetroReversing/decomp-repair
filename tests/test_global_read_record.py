from decomprepair import global_read_record as m
from decomprepair import registry

SOURCE = '''extern s16 D_80100000;
extern u16 D_80100010[];
extern u8 D_80100020[];
extern u8 D_80100030;

void f(void) {
    s32 i;

    for (i = 0; i < 4; i++) {
        if (D_80100000 != 0) {
            D_80100020[D_80100010[i]] = 0;
        }
    }
    g(&D_80100030);
}
'''


def test_a_read_scalar_becomes_a_one_member_record():
    child = [text for family, text in m.variants(SOURCE, 'f') if family == 'global_read_record'][0]
    assert 'extern struct { s16 value; } D_80100000;' in child
    assert 'if (D_80100000.value != 0)' in child


def test_an_indexed_array_becomes_records():
    children = [text for family, text in m.variants(SOURCE, 'f') if family == 'array_element_record']
    assert any('extern struct { u16 value; } D_80100010[];' in text and 'D_80100010[i].value' in text for text in children)


def test_address_taken_and_header_globals_are_left_alone():
    assert not [1 for _, text in m.variants(SOURCE, 'f') if 'struct { u8 value; } D_80100030' in text]
    assert not [1 for _, text in m.variants(SOURCE, 'f', header='extern s16 D_80100000;')
                if 'struct { s16 value; } D_80100000' in text]


def test_declared():
    assert 'global_read_record' in [repair.module for repair in registry.declared()]
