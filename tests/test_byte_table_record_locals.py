"""Records of a byte table reached through address locals and a loaded index, written as the record array."""
from decomprepair import byte_table_record_locals, registry

SOURCE = '''extern char D_80100000[];

void f(void *arg0) {
    u8 *base;
    s32 index;

    base = 0;
    *(((*(u8 *)((s8 *)arg0 + 0x20)) * 6) + D_80100000) = (*(u16 *)((s8 *)arg0 + 0));
    {
        u16 *temp;
        temp = (u16 *)((s8 *)(((*(u8 *)((s8 *)arg0 + 0x20)) * 6) + D_80100000) + 2);
        (*temp) = (u16) (*(u16 *)((s8 *)arg0 + 2));
    }
    do { index = (*(u8 *)((s8 *)arg0 + 0x20)) * 6;
 base = D_80100000;
 (*(u16 *)((s8 *)(base + index) + 4)) = (u16) (*(u16 *)((s8 *)arg0 + 4)); } while (0);
}
'''


def test_every_spelling_of_the_record_becomes_the_array():
    ((family, text),) = byte_table_record_locals.variants(SOURCE, 'f')
    assert family == 'byte_table_record_locals'
    assert 'extern CastRow_D_80100000 D_80100000[];' in text
    for member, offset in (('m0', 0), ('m2', 2), ('m4', 4)):
        assert f'D_80100000[(*(u8 *)((s8 *)arg0 + 0x20))].{member}' in text, offset
    # the address locals and the byte-wide store are gone
    assert 'base' not in text and 'index' not in text and 'temp' not in text and 'char D_80100000' not in text


def test_a_table_the_header_declares_is_left():
    assert byte_table_record_locals.variants(SOURCE, 'f', header='extern char D_80100000[];') == []


def test_a_pointer_local_with_another_use_is_left():
    source = SOURCE.replace('(*temp) = (u16)', 'g(temp);\n        (*temp) = (u16)')
    assert byte_table_record_locals.variants(source, 'f') == []


def test_the_module_declares_itself():
    assert any(byte_table_record_locals.FAMILY in repair.families for repair in registry.declared())
