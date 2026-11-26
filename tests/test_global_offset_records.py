from decomprepair import global_offset_records as g
from decomprepair import registry

SOURCE = '''typedef s32 M2C_UNK;
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern M2C_UNK D_80001000;

void func_80002000(void) {
    s32 var_a0;
    void *temp_v0;

    temp_v0 = (char *)&D_80001000 + 0x100;
    M2C_FIELD(&D_80001000, s16 *, 0x100) = 7;
    M2C_FIELD(temp_v0, s16 *, 2) = 8;
    M2C_FIELD(temp_v0, u8 *, 0x14) = 9;
    M2C_FIELD(temp_v0, s16 *, 0x18) = 10;
    var_a0 = 2;
    do {
        *((char *)&D_80001000 + 0x100 + ((var_a0 & 0xFF) * 0x18)) = 0;
        var_a0 += 1;
    } while ((u32) (var_a0 & 0xFF) < 4U);
}
'''


def test_offsets_become_the_record_array_at_its_own_address():
    family, child = g.variants(SOURCE, 'func_80002000')[0]
    assert family == g.FAMILY
    assert 'extern OffsetRow D_80001100[];' in child
    assert 'char pad4[0x10];\n    u8 m14;' in child
    assert 'D_80001100[0].m0 = 7;' in child
    assert 'D_80001100[0].m14 = 9;' in child
    assert 'D_80001100[1].m0 = 10;' in child
    assert 'D_80001100[var_a0 & 0xFF].m0 = 0;' in child
    assert 'temp_v0' not in child and 'D_80001000' not in child


def test_the_array_as_a_member_at_the_symbol_already_named():
    child = g.variants(SOURCE, 'func_80002000')[1][1]
    assert 'char pad[0x100];\n    OffsetRow rows[0];' in child
    assert 'extern OffsetRowTable D_80001000;' in child
    assert 'D_80001000.rows[0].m2 = 8;' in child


def test_an_alias_used_otherwise_is_left_alone():
    used = SOURCE.replace('var_a0 = 2;', 'func_80003000(temp_v0);\n    var_a0 = 2;')
    assert g.variants(used, 'func_80002000') == []


def test_a_symbol_the_header_declares_is_not_redeclared():
    assert g.variants(SOURCE, 'func_80002000', header='extern char D_80001000[];') == [
        pair for pair in g.variants(SOURCE, 'func_80002000') if 'extern OffsetRow D_80001100[];' in pair[1]]


def test_declared_in_the_registry():
    assert any(entry.module == 'global_offset_records' for entry in registry.declared())
