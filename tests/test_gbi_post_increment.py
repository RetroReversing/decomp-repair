"""m2c's per-command display-list writes through a `Gfx **` parameter, written as the SDK's `(*gfxp)++` macros."""
from decomprepair import gbi_post_increment as p
from decomprepair import registry

SOURCE = '''void draw(void **arg0, s32 arg1) {
    s32 temp_a0;
    void *temp_v1;
    void *temp_v1_2;
    void *temp_v1_3;

    temp_v1 = *arg0;
    *arg0 = temp_v1 + 8;
    M2C_FIELD(temp_v1, s32 *, 0) = 0xE7000000;
    M2C_FIELD(temp_v1, s32 *, 4) = 0;
    temp_v1_2 = *arg0;
    *arg0 = temp_v1_2 + 8;
    temp_a0 = (arg1 << 5) + 0x1F;
    M2C_FIELD(temp_v1_2, s32 *, 0) = (s32) (temp_a0 | 0xF4000000);
    M2C_FIELD(temp_v1_2, s32 *, 4) = (s32) (temp_a0 << 2);
    temp_v1_3 = *arg0;
    *arg0 = temp_v1_3 + 8;
    M2C_FIELD(temp_v1_3, s32 *, 0) = (s32) (temp_a0 | 0xF2000000);
    M2C_FIELD(temp_v1_3, M2C_UNK **, 4) = &table;
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'draw')]


def test_each_command_becomes_one_post_increment_block():
    first = texts(SOURCE)[0]
    assert ('{ Gfx *_g = (Gfx *)((*(Gfx **)arg0)++); _g->words.w0 = (0xE7000000); '
            '_g->words.w1 = (unsigned int)(0); }') in first
    assert first.count('Gfx *_g') == 3 and '*arg0 = temp_v1' not in first
    assert first.startswith('typedef union { struct { unsigned int w0; unsigned int w1; } words;')
    # the temporary two commands read stays, ahead of its command
    assert 'temp_a0 = (arg1 << 5) + 0x1F;' in first


def test_a_temporary_only_command_words_read_is_written_into_them():
    last = texts(SOURCE)[-1]
    assert 'temp_a0 = ' not in last
    assert '_g->words.w0 = ((s32) (((arg1 << 5) + 0x1F) | 0xF2000000));' in last


def test_a_temporary_whose_operand_changes_is_left_alone():
    source = SOURCE.replace('    temp_v1_3 = *arg0;', '    arg1 += 1;\n    temp_v1_3 = *arg0;')
    assert all('temp_a0 = (arg1 << 5) + 0x1F;' in text for text in texts(source))


def test_nothing_without_the_shape_and_it_is_registered():
    assert p.variants('void draw(s32 *a) {\n    *a = 1;\n}\n', 'draw') == []
    assert any(p.FAMILY in repair.families for repair in registry.declared())
