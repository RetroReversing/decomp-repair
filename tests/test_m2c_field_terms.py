"""m2c's `M2C_FIELD(base, T *, offset)` reads and stores like the cast spelling, not like a call."""
from decomprepair import commuted_factor, staged_store_rise, statement_fence, temporary_hoist_repairs
from decomprepair import expression_terms as terms

HEAD = 'typedef signed int s32;\ns32 lookup(s32);\nextern s32 D_G;\n'
SOURCE = HEAD + '''void f(void *o, void *self, s32 i) {
    s32 next;
    s32 scale;

    M2C_FIELD(o, s32 *, 0x10) = (M2C_FIELD(self, s32 *, 4) * i + D_G) * 3;
    next = lookup(M2C_FIELD(o, s32 *, 8));
    M2C_FIELD(o, s32 *, 0x1C) = 2;
    M2C_FIELD(o, s32 *, 0x20) = M2C_FIELD(self, s32 *, 0x20);
    M2C_FIELD(o, s32 *, 0x24) = M2C_FIELD(self, s32 *, 0x24) + 2;
    scale = M2C_FIELD(self, s32 *, 0x28) * M2C_FIELD(self, s32 *, 0x2C);
    D_G = next + scale + scale;
}
'''


def test_the_macro_is_read_as_a_field_with_its_type():
    text = 'M2C_FIELD(self, volatile s32 *, 0x20)'
    node = terms.parse(text, 0, len(text), ('s32',))
    assert node.kind == 'field' and node.info == ('volatile', 's32', '*') and (node.start, node.end) == (0, len(text))
    types = terms.Types(SOURCE, 'f')
    assert types.of(node).spelling == 's32'
    assert terms.pure(node) and terms.names(node) == {'self'}


def test_a_type_that_is_no_pointer_is_left_unread():
    text = 'M2C_FIELD(self, s32, 0x20)'
    assert terms.parse(text, 0, len(text), ('s32',)) is None


def test_the_expression_families_offer_on_the_macro_spelling():
    hoisted = [text for _, text in temporary_hoist_repairs.variants(SOURCE, 'f')]
    assert any('= M2C_FIELD(self, s32 *, 4)' in text for text in hoisted)
    assert staged_store_rise.variants(SOURCE, 'f')
    assert any('M2C_FIELD(self, s32 *, 0x2C) * M2C_FIELD(self, s32 *, 0x28)' in text
               for _, text in commuted_factor.variants(SOURCE, 'f'))
    assert any(family == 'fence_statement_deep' for family, _ in statement_fence.variants(
        HEAD + '''void f(void *self) {
    s32 scale;

    scale = M2C_FIELD(self, s32 *, 0x28) * 12;
    D_G = scale;
    lookup(scale);
}
''', 'f'))


def test_a_volatile_field_is_not_held():
    source = SOURCE.replace('M2C_FIELD(self, s32 *, 4)', 'M2C_FIELD(self, volatile s32 *, 4)')
    assert not any('= M2C_FIELD(self, volatile s32 *, 4);' in text
                   for _, text in temporary_hoist_repairs.variants(source, 'f'))
