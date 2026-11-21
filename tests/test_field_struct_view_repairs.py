from decomprepair import field_struct_view_repairs as repairs

PREFIX = '#ifndef M2C_DEFINES\n#define M2C_DEFINES\n' + repairs.POINTER_FORM + '\n#endif\n'
BODY = 'void f(void *a) {\n    M2C_FIELD(a, s32 *, 0x58) = M2C_FIELD(a, s32 *, 0x5C);\n}\n'


def test_the_macro_becomes_a_struct_member_read_and_nothing_else_changes():
    (family, text), = repairs.variants(PREFIX + BODY, 'f')
    assert family == repairs.FAMILY and repairs.MEMBER_FORM in text
    assert repairs.POINTER_FORM not in text
    assert text.endswith(BODY) and text.count('#define M2C_FIELD') == 1


def test_a_function_without_fields_or_a_foreign_macro_is_declined():
    assert repairs.variants(PREFIX + 'void f(void *a) {\n    g(a);\n}\n', 'f') == []
    assert repairs.variants(BODY, 'f') == []
    assert repairs.variants(PREFIX.replace('(*(type_ptr)', '(*(volatile type_ptr)') + BODY, 'f') == []


def test_the_member_form_is_not_rewritten_again():
    (_, text), = repairs.variants(PREFIX + BODY, 'f')
    assert repairs.variants(text, 'f') == []


def test_each_access_can_go_back_to_a_pointer_dereference_stores_first():
    (_, member), = repairs.variants(PREFIX + BODY, 'f')
    sites = repairs.site_variants(member, 'f')
    assert len(sites) == 2 and all(family == repairs.SITE_FAMILY for family, _ in sites)
    first = sites[0][1]
    assert repairs.POINTER_SITE in first and 'M2C_FIELD_PTR(a, s32 *, 0x58) =' in first
    assert 'M2C_FIELD(a, s32 *, 0x5C)' in first and first.count('M2C_FIELD_PTR(') == 1 + 1  # its use, and the define


def test_without_the_member_form_there_are_no_site_candidates():
    assert repairs.site_variants(PREFIX + BODY, 'f') == []


PRINTED_SOURCE = """extern void *rs;
void setup(void *cam, s32 i) {
    void *row;
    row = rs + i;
    *((s16 *) (((char *) row) + 0x300)) = (s16) ((s32) (*((f32 *) (((char *) cam) + 0x60))));
    *((s16 *) (((char *) row) + 0x302)) = 0;
    use(*((s32 *) (((char *) cam) + 0x100)));
}
"""


def test_the_printed_spelling_of_a_field_becomes_the_member_form():
    from decomprepair.field_struct_view_repairs import printed_variants
    found = dict.fromkeys(c for _, c in printed_variants(PRINTED_SOURCE, 'setup'))
    everything = max(found, key=lambda c: c.count('->v'))
    assert everything.count('->v') == 4 and '*((s16 *)' not in everything
    assert 'typedef struct { s16 v; } Field_s16;' in everything and 'typedef struct { f32 v; } Field_f32;' in everything
    assert everything.index('typedef') < everything.index('void setup(')
    assert '(((Field_s16 *) (((char *) row) + 0x300))->v) = (s16)' in everything
    stores = min(found, key=lambda c: c.count('->v'))
    assert stores.count('->v') >= 1 and len(found) >= 3


def test_the_printed_member_form_leaves_m2c_macro_sources_to_the_macro_family():
    from decomprepair.field_struct_view_repairs import printed_variants
    macro = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))\n'
    assert not printed_variants(macro + PRINTED_SOURCE, 'setup')
    assert not printed_variants('void f(void) { g(); }\n', 'f')
