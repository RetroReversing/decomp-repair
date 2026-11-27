from decomprepair import registry
from decomprepair.stored_constant_operand import FAMILY, variants

SOURCE = """typedef struct { s16 scale, scaleY; u8 flag; u16 type; } Ent;
extern s32 sizes[];
void f(Ent *self) {
    u32 size;
    self->scale = self->scaleY = 0x6000;
    size = sizes[self->type] * 0x6000;
    g(size);
}
"""
CELL = """extern s32 sizes;
void f(void *p) {
    u32 size;
    M2C_FIELD(p, s16 *, 0xC) = 0x6000;
    size = *((M2C_FIELD(p, u16 *, 0x6A) * 4) + &sizes) * 0x6000;
    g(size);
}
"""


def children(source):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_factor_is_read_from_either_stored_member():
    made = children(SOURCE)
    assert any('* self->scale;' in text for text in made)
    assert any('* self->scaleY;' in text for text in made)


def test_a_cell_of_an_m2c_draft():
    (child,) = children(CELL)
    assert '+ &sizes) * M2C_FIELD(p, s16 *, 0xC);' in child


def test_a_value_the_member_cannot_hold_stays():
    assert not children(SOURCE.replace('0x6000', '0x9000'))


def test_not_past_a_call_or_a_second_store():
    assert not children(SOURCE.replace('size = sizes', 'h(self);\n    size = sizes'))
    assert not children(SOURCE.replace('size = sizes', 'self->scale = self->scaleY = 1;\n    size = sizes'))


def test_it_is_registered():
    assert FAMILY in {family for repair in registry.declared() for family in repair.families}
