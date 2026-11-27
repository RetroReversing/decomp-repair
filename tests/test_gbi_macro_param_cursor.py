from decomprepair.gbi_macro_commands import PARAMETER_FAMILY, variants

SOURCE = """void draw(void **arg0, s32 arg1, s32 arg4) {
    void *temp_a3;
    void *temp_a3_2;
    s32 temp_t0;

    temp_a3 = *arg0;
    temp_a3_2 = temp_a3 + 8;
    *((s32 *) (((char *) temp_a3) + 0)) = 0xFD100000;
    *((s32 *) (((char *) temp_a3) + 4)) = arg4;
    temp_t0 = arg1 & 0xFFF; temp_a3 = temp_a3_2 + 8;
    *((s32 *) (((char *) temp_a3_2) + 0)) = 0xE8000000;
    *((s32 *) (((char *) temp_a3_2) + 4)) = 0;
    arg4 = temp_t0 + 1;
    *((s32 *) (((char *) (temp_a3_2 + 8)) + 0)) = temp_t0 | 0xF4000000;
    *((s32 *) (((char *) (temp_a3_2 + 8)) + 4)) = arg4 & 0xFFF;
    *arg0 = temp_a3 + 8;
}
"""


def children(source):
    return [text for family, text in variants(source, 'draw') if family == PARAMETER_FAMILY]


def test_pointer_argument_cursor_becomes_macros_on_a_local_copy():
    child = children(SOURCE)[0]
    assert '{ Gfx *gfx = (*(Gfx **) arg0);' in child
    assert 'gDPSetTextureImage(gfx++, 0, 2, 1, arg4);' in child
    assert 'gDPTileSync(gfx++);' in child
    assert '(*(Gfx **) arg0) = gfx; }' in child
    assert '__repair_cursor' not in child


def test_register_reused_after_a_word_read_it_gets_its_own_name():
    child = children(SOURCE)[0]
    # the first word still reads the argument; the later assignment and its reader use a new local
    assert 's32 arg4_w2;' in child
    assert 'arg4_w2 = temp_t0 + 1;' in child
    assert 'temp_t0 | 0xF4000000, arg4_w2 & 0xFFF' in child


def test_fast3d_texture_rectangle_halves():
    source = SOURCE.replace('temp_t0 | 0xF4000000;', '0xE40A0140;').replace(
        '*((s32 *) (((char *) (temp_a3_2 + 8)) + 4)) = arg4 & 0xFFF;\n    *arg0 = temp_a3 + 8;',
        '*((s32 *) (((char *) (temp_a3_2 + 8)) + 4)) = 0;\n'
        '    *((s32 *) (((char *) temp_a3) + 8)) = 0xB4000000;\n'
        '    *((s32 *) (((char *) temp_a3) + 12)) = 0;\n'
        '    *((s32 *) (((char *) temp_a3) + 16)) = 0xB3000000;\n'
        '    *((s32 *) (((char *) temp_a3) + 20)) = 0x04000400;\n'
        '    *arg0 = temp_a3 + 24;')
    child = children(source)[0]
    assert 'gSPTextureRectangleF3D(gfx++, ' in child
    assert 'gImmp1(pkt, 0xB4,' in child


def test_a_parameter_that_is_not_written_back_is_left_alone():
    assert children(SOURCE.replace('*arg0 = temp_a3 + 8;', '')) == []
