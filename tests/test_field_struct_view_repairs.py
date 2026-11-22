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


SYMBOL_SOURCE = """typedef struct { s16 slot; u16 flags; } Entry;
extern u16 D_800C02D8;
extern u8 D_800C02DC;
extern Entry *D_800C02D4;
void setup(s32 idx)
{
  s32 offset;
  u16 size;
  u8 count;
  Entry *first;
  offset = idx * 32;
  first = *((Entry **) (((u8 *) (&D_800C02D4)) + offset));
  size = *((u16 *) (((u8 *) (&D_800C02D8)) + offset));
  count = *((u8 *) ((&D_800C02DC) + offset));
  use(first, size, count);
}
"""


def test_a_symbol_based_field_with_a_variable_offset_becomes_the_member_form():
    # An N64 map-table setup (KMC gcc 2.7.2) wrote its record fields as `*((u16 *) (((u8 *) (&D_800C02D8)) + offset))`:
    # no `char` cast, the address of a symbol as the base, a variable offset. None of that matched the printed form, so
    # the member form (which moves a load above a store to a scalar global, as the original's `table[i].size` did) was
    # never offered; one member read plus two loop and ordering changes took the function from 85 to 0.
    from decomprepair.field_struct_view_repairs import printed_variants
    found = dict.fromkeys(c for _, c in printed_variants(SYMBOL_SOURCE, 'setup'))
    everything = max(found, key=lambda c: c.count('->v'))
    assert everything.count('->v') == 3 and '*((u16 *)' not in everything and '*((u8 *)' not in everything
    assert '(((Field_u16 *) (((u8 *) (&D_800C02D8)) + offset))->v)' in everything
    assert '(((Field_u8 *) ((&D_800C02DC) + offset))->v)' in everything
    assert '(((Field_MapEntry_' not in everything and 'typedef struct { Entry * v; } Field_Entry;' in everything
    assert '(((Field_Entry *) (((u8 *) (&D_800C02D4)) + offset))->v)' in everything
    # each symbol's accesses alone are offered too
    assert any(c.count('->v') == 1 and 'Field_u16 *)' in c for c in found)


COMPACT_SOURCE = """extern void *sRenderState;
extern unsigned int sUsed;
void emit(int n) {
    int base;
    sUsed = n + 1;
    base = (*(s32 *)((char *)(sRenderState) + 0x74C)) + (n << 6);
    use(base, *(u16 *)((char *)sRenderState + 0x360), *(s32 *)((char *)(sRenderState) + 0x74C));
}
"""


def test_the_compact_spelling_of_a_global_pointer_field_becomes_the_member_form():
    # An N64 matrix-emit function (KMC gcc 2.7.2, 95 instructions) read `*(s32 *)((char *)(sRenderState) + 0x74C)` after
    # a store to the scalar global `sUsed`. As a pointer dereference the first scheduler kept the load below the store,
    # one slot after the target's (60); as a member of a one-member record (a MEM_IN_STRUCT reference, which sched.c's
    # true_dependence does not tie to a scalar global's store) it moved above it: exact. The printed pattern wanted
    # m2c's `(((char *) base) + off)` spacing and missed this spelling, so the member form was never offered.
    found = dict.fromkeys(c for _, c in repairs.printed_variants(COMPACT_SOURCE, 'emit'))
    everything = max(found, key=lambda c: c.count('->v'))
    assert everything.count('->v') == 3 and 'typedef struct { s32 v; } Field_s32;' in everything
    assert '(((Field_s32 *) ((char *)(sRenderState) + 0x74C))->v)' in everything
    assert '(((Field_u16 *) ((char *)sRenderState + 0x360))->v)' in everything
    assert not repairs.printed_variants(everything, 'emit')
