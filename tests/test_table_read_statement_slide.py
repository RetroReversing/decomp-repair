from decomprepair import registry
from decomprepair.table_read_statement_slide import FAMILY, variants

SOURCE = """typedef struct { s32 timer; s32 size; s32 count; u16 type; } Rec;
extern u32 sizes[];
void f(void *p) {
    ((Rec *) p)->timer = 0;
    ((Rec *) p)->size = (u32) (sizes[((Rec *) p)->type] * 0x1800) >> 0xC;
}
"""
FAR = """extern u32 sizes[];
void f(void *p, s32 n) {
    M2C_FIELD(p, s32 *, 0x38) = n;
    M2C_FIELD(p, s32 *, 0x34) = (n + 1) * 0xB;
    M2C_FIELD(p, s32 *, 0x1C) = 0x200;
    M2C_FIELD(p, u32 *, 0x3C) = (u32) (sizes[M2C_FIELD(p, u16 *, 0x6A)] << 0xC) >> 0xC;
}
"""


def children(source):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def at(text, *marks):
    return sorted(marks, key=text.index)


def test_a_table_read_store_passes_a_store_to_another_member():
    (child,) = children(SOURCE)
    assert child.index('->size =') < child.index('->timer = 0;')


def test_the_table_read_slides_two_statements_up():
    assert any(at(text, '0x34)', '0x1C)', 'sizes[M2C') == ['sizes[M2C', '0x34)', '0x1C)'] for text in children(FAR))


def test_a_value_read_through_its_address_is_the_same_table():
    spelled = SOURCE.replace('extern u32 sizes[];', 'extern s32 sizes;').replace('sizes[', '(&sizes)[')
    (child,) = children(spelled)
    assert child.index('->size =') < child.index('->timer = 0;')
    assert not children(spelled.replace('->timer = 0;', '->timer = sizes;'))


def test_a_store_to_the_index_or_a_written_table_stays():
    assert not children(SOURCE.replace('->timer = 0;', '->type = 0;'))
    assert not children(SOURCE.replace('->timer = 0;', '->timer = sizes[0]++;'))
    assert not children(SOURCE.replace('->timer = 0;', '->timer = 0; sizes[1] = 2;'))
    assert not children(SOURCE.replace('->timer = 0;', '->timer = (s32) &sizes[1];'))
    assert not children(SOURCE.replace('extern u32 sizes[];', 'extern volatile u32 sizes[];'))


def test_a_call_is_a_barrier_and_the_module_declares_itself():
    assert not children(SOURCE.replace('((Rec *) p)->timer = 0;', 'g();'))
    assert any(repair.module.endswith('table_read_statement_slide') for repair in registry.declared())
