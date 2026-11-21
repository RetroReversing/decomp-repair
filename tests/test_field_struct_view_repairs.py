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
