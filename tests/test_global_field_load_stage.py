from decomprepair.global_field_load_stage import FAMILY, NAME, variants

SOURCE = """
void draw(void *arg0) {
    f32 sp50[16];
    u32 var_a0;
    s32 temp_s1_2;
    sp50[0] = M2C_FIELD(arg0, f32 *, 0) * 0.015625f;
    sp50[4] = M2C_FIELD(arg0, f32 *, 4) * 0.015625f;
    var_a0 = sPoolUsed + 1;
    sPoolUsed = var_a0;
    temp_s1_2 = M2C_FIELD(sRenderState, s32 *, 0x74C) + (var_a0 << 6);
    emit(sp50, temp_s1_2);
}
"""


def test_reads_the_global_field_first_in_its_block():
    [(family, revised)] = variants(SOURCE, 'draw')
    assert family == FAMILY
    assert f's32 {NAME};' in revised
    assert revised.index(f'{NAME} = M2C_FIELD(sRenderState, s32 *, 0x74C);') < revised.index('sp50[0] =')
    assert f'temp_s1_2 = {NAME} + (var_a0 << 6);' in revised
    assert variants(revised, 'draw') == []


def test_leaves_locals_calls_and_stores_through_pointers_alone():
    assert variants(SOURCE.replace('sRenderState', 'arg0'), 'draw') == []
    assert variants(SOURCE.replace('var_a0 = sPoolUsed + 1;', 'var_a0 = get();'), 'draw') == []
    assert variants(SOURCE.replace('sPoolUsed = var_a0;', 'M2C_FIELD(arg0, s32 *, 8) = var_a0;'), 'draw') == []
    assert variants(SOURCE.replace('sPoolUsed = var_a0;', 'sRenderState = var_a0;'), 'draw') == []
    two = SOURCE.replace('    sp50[4] = M2C_FIELD(arg0, f32 *, 4) * 0.015625f;\n', '').replace('    sp50[0] = M2C_FIELD(arg0, f32 *, 0) * 0.015625f;\n', '')
    assert variants(two, 'draw') == []
