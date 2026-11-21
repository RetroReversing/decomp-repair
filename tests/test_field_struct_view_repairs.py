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
