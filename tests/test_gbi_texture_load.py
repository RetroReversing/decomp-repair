"""m2c's draft of a texture loader on a returned cursor, as the composite load macros (a homemade icon routine)."""
from decomprepair import gbi_texture_load, registry

DRAFT = """extern char gIconPalettes[];

void *draw_icon(void *arg0, void *arg1, s32 arg2) {
    s32 var_a0;
    u32 temp_a1;
    u8 temp_a0;
    u8 temp_t0;
    u8 temp_v1;
    void *temp_s0;
    void *temp_s0_2;
    void *temp_s0_3;
    void *temp_s0_4;
    void *temp_s0_5;
    void *temp_s0_6;
    void *temp_s0_7;
    void *temp_s0_8;
    void *temp_s0_9;
    void *temp_s0_10;
    void *temp_s0_11;
    void *temp_s0_12;
    void *temp_s0_13;
    void *var_a1;
    void *var_s0;
    void *var_v0;

    temp_t0 = M2C_FIELD(arg1, u8 *, 0xF);
    temp_v1 = M2C_FIELD(arg1, u8 *, 0xE);
    switch (temp_v1) {
    case 4:
        temp_s0 = arg0 + 8;
        temp_s0_2 = temp_s0 + 8;
        temp_s0_3 = temp_s0_2 + 8;
        temp_s0_4 = temp_s0_3 + 8;
        temp_s0_5 = temp_s0_4 + 8;
        temp_s0_6 = temp_s0_5 + 8;
        temp_s0_7 = temp_s0_6 + 8;
        temp_s0_8 = temp_s0_7 + 8;
        temp_s0_9 = temp_s0_8 + 8;
        temp_s0_10 = temp_s0_9 + 8;
        temp_s0_11 = temp_s0_10 + 8;
        temp_s0_12 = temp_s0_11 + 8;
        temp_s0_13 = temp_s0_12 + 8;
        M2C_FIELD(arg0, s32 *, 0) = 0xE3001001;
        M2C_FIELD(arg0, s32 *, 4) = 0x8000;
        M2C_FIELD(arg0, s32 *, 8) = 0xFD100000;
        M2C_FIELD(temp_s0, s32 *, 4) = (s32) M2C_FIELD(((temp_t0 * 8) + gIconPalettes), s32 *, 4);
        M2C_FIELD(temp_s0, s32 *, 8) = 0xE8000000;
        M2C_FIELD(temp_s0_2, s32 *, 4) = 0;
        M2C_FIELD(temp_s0_2, s32 *, 8) = 0xF5000100;
        M2C_FIELD(temp_s0_3, s32 *, 4) = 0x07000000;
        M2C_FIELD(temp_s0_3, s32 *, 8) = 0xE6000000;
        M2C_FIELD(temp_s0_4, s32 *, 4) = 0;
        M2C_FIELD(temp_s0_4, s32 *, 8) = 0xF0000000;
        M2C_FIELD(temp_s0_5, s32 *, 4) = 0x0703C000;
        M2C_FIELD(temp_s0_5, s32 *, 8) = 0xE7000000;
        M2C_FIELD(temp_s0_6, s32 *, 4) = 0;
        M2C_FIELD(temp_s0_6, s32 *, 8) = 0xFD500000;
        M2C_FIELD(temp_s0_7, s32 *, 4) = (s32) M2C_FIELD(arg1, s32 *, 0x10);
        M2C_FIELD(temp_s0_7, s32 *, 8) = 0xF5500000;
        M2C_FIELD(temp_s0_8, s32 *, 4) = (s32) ((arg2 << 0xE) | ((arg2 * 0x10) | 0x07000000));
        M2C_FIELD(temp_s0_8, s32 *, 8) = 0xE6000000;
        M2C_FIELD(temp_s0_9, s32 *, 4) = 0;
        M2C_FIELD(temp_s0_9, s32 *, 8) = 0xF3000000;
        temp_a0 = M2C_FIELD(arg1, u8 *, 0xC);
        temp_a1 = temp_a0 >> 4;
        var_a0 = 0x800;
        if (temp_a1 != 0) {
            var_a0 = temp_a1 + 0x7FF;
        }
        M2C_FIELD(temp_s0_10, s32 *, 4) = (s32) (var_a0 / (s32) temp_a1);
        M2C_FIELD(temp_s0_10, s32 *, 8) = 0xE7000000;
        M2C_FIELD(temp_s0_11, s32 *, 4) = 0;
        var_a1 = temp_s0_11 + 8;
        var_s0 = temp_s0_13 + 8;
        M2C_FIELD(var_a1, s32 *, 4) = (s32) ((arg2 << 0xE) | (arg2 * 0x10));
block_9:
        M2C_FIELD(var_a1, s32 *, 0) = (s32) (((((M2C_FIELD(arg1, u8 *, 0xC) >> 1) + 7) >> 3) << 9) | 0xF5400000);
        M2C_FIELD(temp_s0_13, s32 *, 0) = 0xF2000000;
        M2C_FIELD(temp_s0_13, s32 *, 4) = (s32) (((((M2C_FIELD(arg1, u8 *, 0xC) - 1) * 4) & 0xFFF) << 0xC) | (((M2C_FIELD(arg1, u8 *, 0xD) - 1) * 4) & 0xFFF));
        var_v0 = var_s0;
        break;
    default:
        var_v0 = arg0;
        break;
    }
    return var_v0;
}
"""


def _children():
    return dict(gbi_texture_load.variants(DRAFT, 'draw_icon'))


def test_the_arm_is_written_as_the_composite_macros():
    plain = _children()['gbi_texture_load']
    assert 'gDPSetTextureLUT(arg0++, 0x8000);' in plain
    assert 'gDPLoadTLUT_pal16(arg0++, 0, M2C_FIELD(((temp_t0 * 8) + gIconPalettes), s32 *, 4));' in plain
    assert ('gDPLoadTextureBlock_4b(arg0++, M2C_FIELD(arg1, s32 *, 0x10), 2, M2C_FIELD(arg1, u8 *, 0xC), '
            'M2C_FIELD(arg1, u8 *, 0xD), 0, 0, 0, arg2, arg2, 0, 0);') in plain
    assert 'Gfx *draw_icon(Gfx *arg0, void *arg1' in plain
    body = plain[plain.index('Gfx *draw_icon'):]
    assert 'temp_s0 = ' not in body and 'var_v0' not in body.replace('void *var_v0;', '')
    assert body.rstrip().endswith('return arg0;\n}')


def test_the_chain_child_widens_the_index_and_reads_a_record():
    children = _children()
    assert list(children)[0] == 'gbi_texture_load_chain'
    assert 's32 temp_t0;' in children['gbi_texture_load_wide']
    assert ('((struct { char pad0[4]; s32 data; } *) gIconPalettes)[temp_t0].data'
            in children['gbi_texture_load_chain'])


def test_an_unknown_command_or_a_value_read_later_gives_nothing():
    assert gbi_texture_load.variants(DRAFT.replace('0xE8000000', '0xDE000000'), 'draw_icon') == []
    later = DRAFT.replace('    return var_v0;\n}', '    gLast = temp_a1;\n    return var_v0;\n}')
    assert gbi_texture_load.variants(later, 'draw_icon') == []


def test_it_is_registered():
    assert any(entry.module.endswith('gbi_texture_load') for entry in registry.declared())
