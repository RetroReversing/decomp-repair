"""A cursor parameter that is returned, written as Gbi macros on `Gfx *`."""
from decomprepair import gbi_value_cursor as g
from decomprepair import registry

DRAFT = """
extern s32 gMode;

void *build(void *arg0, s32 arg1) {
    void *temp_t0;
    void *temp_t1;
    void *temp_t2;
    void *var_a0;
    void *var_v0;
    s32 var_v1;

    switch (arg1) {
    case 1:
        temp_t0 = arg0 + 8;
        M2C_FIELD(arg0, s32 *, 4) = 0;
        M2C_FIELD(arg0, s32 *, 0) = 0xE7000000;
        temp_t1 = temp_t0 + 8;
        var_v1 = 0;
        var_a0 = temp_t0;
        var_v0 = temp_t1;
block_3:
        M2C_FIELD(var_a0, s32 *, 4) = var_v1;
        M2C_FIELD(var_a0, s32 *, 0) = 0xE6000000;
        gMode = 1;
        break;
    case 2:
        temp_t2 = arg0 + 8;
        M2C_FIELD(arg0, s32 *, 0) = 0xE8000000;
        M2C_FIELD(arg0, s32 *, 4) = 0;
        var_v1 = 0;
        var_a0 = temp_t2;
        var_v0 = temp_t2 + 8;
        goto block_3;
    default:
        var_v0 = arg0;
        break;
    }
    return var_v0;
}
"""


def test_shared_tail_is_copied_and_the_commands_become_macros():
    family, text = g.variants(DRAFT, 'build')[0]
    assert family == 'gbi_value_cursor'
    assert 'void *build(Gfx *arg0, s32 arg1)' in text
    assert text.count('gDPPipeSync(arg0++);') == 1 and text.count('gDPTileSync(arg0++);') == 1
    assert text.count('gDPLoadSync(arg0++);') == 2
    assert 'block_3' not in text and 'var_v0' not in text and '__repair' not in text
    assert text.count('return arg0;') == 1


def test_a_cursor_read_after_the_result_moved_is_left_alone():
    source = DRAFT.replace('var_v0 = temp_t1;\n', 'var_v0 = temp_t1;\n        gMode = M2C_FIELD(arg0, s32 *, 0);\n')
    assert g.variants(source, 'build') == []


def test_a_command_that_cannot_be_rewritten_leaves_no_child():
    # the second word of the first command is never stored: its run is no run, so `+ 8` would stay on the cursor
    source = DRAFT.replace('        M2C_FIELD(arg0, s32 *, 4) = 0;\n        M2C_FIELD(arg0, s32 *, 0) = 0xE7000000;\n',
                           '        M2C_FIELD(arg0, s32 *, 0) = 0xE7000000;\n')
    assert g.variants(source, 'build') == []


def test_the_module_declares_itself():
    assert any(r.module.endswith('gbi_value_cursor') for r in registry.declared())
