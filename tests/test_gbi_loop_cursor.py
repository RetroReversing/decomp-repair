import re

from decomprepair import gbi_loop_cursor as g

# m2c's shape of a display-list builder whose cursor is the caller's (`s32 *arg0` for a `Gfx **`): the cursor local, a
# loop base set four bytes before it that steps eight bytes per command, the cursor advanced per arm, and a texture
# rectangle whose first word is in one of two arms and whose other two words follow the join (a homemade function)
DRAFT = '''extern s32 gFlag;
void build(s32 *arg0, s32 arg1, s32 arg2, u32 arg3, u32 arg4, s32 arg5, f32 arg6)
{
    s32 *sp4;
    s32 var_t1;
    s32 var_t1_2;
    u32 var_t4;
    s32 temp_t7;
    s32 temp_a0;
    s32 var_a0_2;
    f32 var_fv0;
    void *var_t0;
    void *temp_t0;
    void *var_t0_2;
    void *temp_t0_2;
    void *var_t0_3;

    sp4 = arg0;
    var_t1 = *arg0;
    var_t4 = arg3;
    temp_t7 = (arg5 & 7) << 0x15;
    if (var_t4 < arg4) {
        var_t0 = var_t1 - 4;
        do {
            temp_t0 = var_t0 + 8;
            if (arg2 == 0) {
                temp_a0 = ((var_t4 >> 3) & 0x1FF) << 9;
                var_t1_2 = var_t1 + 0x10;
                M2C_FIELD(var_t0, s32 *, 8) = arg1;
                M2C_FIELD(temp_t0, s32 *, -4) = (s32) (temp_t7 | (((arg3 - 1) & 0xFFF) | 0xFD080000));
                var_t0_2 = temp_t0 + 8;
                M2C_FIELD(var_t0_2, s32 *, -4) = (s32) (temp_t7 | (temp_a0 | 0xF5080000));
                M2C_FIELD(temp_t0, s32 *, 8) = 0x07080200;
            } else {
                var_t1_2 = var_t1 + 0x10;
                M2C_FIELD(var_t0, s32 *, 8) = arg1;
                M2C_FIELD(temp_t0, s32 *, -4) = (s32) (temp_t7 | (((arg4 - 1) & 0xFFF) | 0xFD080000));
                var_t0_2 = temp_t0 + 8;
                M2C_FIELD(var_t0_2, s32 *, -4) = 0xE7000000;
                M2C_FIELD(temp_t0, s32 *, 8) = 0;
            }
            temp_t0_2 = var_t0_2 + 8;
            if (gFlag != 0) {
                var_fv0 = var_t4 * 32.0f;
                M2C_FIELD(temp_t0_2, s32 *, -4) = 0xE4000000 | ((var_t4 * 8) & 0xFFF);
                M2C_FIELD(var_t0_2, s32 *, 8) = (var_t4 & 0xFFF) << 0xC;
                var_t0_3 = temp_t0_2 + 8;
                var_t1 = var_t1_2 + 0x18;
                var_a0_2 = 0x04000200;
            } else {
                var_fv0 = var_t4 * 32.0f;
                M2C_FIELD(temp_t0_2, s32 *, -4) = 0xE4000000 | ((var_t4 * 4) & 0xFFF);
                M2C_FIELD(var_t0_2, s32 *, 8) = (var_t4 & 0xFFF) << 0xC;
                var_t0_3 = temp_t0_2 + 8;
                var_t1 = var_t1_2 + 0x18;
                var_a0_2 = 0x04000400;
            }
            M2C_FIELD(var_t0_3, s32 *, -4) = 0xE1000000;
            M2C_FIELD(var_t0_3, s32 *, 0) = (s32) (((s32) var_fv0 << 0x10) | ((s32) var_fv0 & 0xFFFF));
            var_t0 = var_t0_3 + 8;
            M2C_FIELD(var_t0, s32 *, -4) = 0xF1000000;
            M2C_FIELD(var_t0_3, s32 *, 8) = var_a0_2;
            var_t4 += 1;
        } while (var_t4 < arg4);
    }
    *sp4 = var_t1;
}
'''


def _out(source=DRAFT, name='build', which=0):
    found = g.variants(source, name)
    assert [family for family, _ in found][:1] == ['gbi_loop_cursor']
    text = found[which][1]
    return text[text.index('void build'):]


def test_the_two_pointer_chains_become_the_sdk_macros_on_one_cursor():
    body = _out()
    assert 'void build(Gfx **arg0,' in body
    assert 'gfx = (Gfx *) *arg0;' in body and '*arg0 = gfx;' in body
    assert 'gDPSetTextureImage(gfx++, arg5, 1, arg3, arg1);' in body
    assert 'gDPSetTextureImage(gfx++, arg5, 1, arg4, arg1);' in body
    assert 'gDPSetTile(gfx++, arg5, 1, var_t4 >> 3, 0, 7, 0, 2, 0, 0, 2, 0, 0);' in body
    assert 'gDPPipeSync(gfx++);' in body
    for gone in ('M2C_FIELD', 'var_t0', 'temp_t0', 'var_t1', 'sp4', 'temp_t7', 'temp_a0'):
        assert gone not in body


def test_a_rectangle_split_over_an_if_else_and_its_join_is_written_whole_in_each_arm():
    body = _out()
    hires = 'gSPTextureRectangle(gfx++, var_t4 * 4, 0, 0, 0, 0, (s32) var_fv0, (s32) var_fv0, 0x400, 0x200);'
    assert body.count('gSPTextureRectangle(') == 2
    assert '0x400, 0x200);' in body and '0x400, 0x400);' in body
    assert hires.split('(')[0] in body
    # the float words keep the integer conversion the draft wrote (the macro's own cast is a different instruction)
    assert body.count('(s32) var_fv0') == 4
    # the float is still computed before the macro that reads it
    assert body.index('var_fv0 = var_t4 * 32.0f;') < body.index('gSPTextureRectangle(')


def test_the_words_are_the_ones_the_draft_wrote_in_the_order_it_wrote_them():
    body = _out()
    first = body.index('gDPSetTextureImage')
    assert [m for m in re.findall(r'(gDP\w+|gSP\w+)\(gfx\+\+', body[first:])] == [
        'gDPSetTextureImage', 'gDPSetTile', 'gDPSetTextureImage', 'gDPPipeSync', 'gSPTextureRectangle', 'gSPTextureRectangle']


def test_an_advance_that_differs_from_the_base_steps_is_left_alone():
    # five commands of eight bytes, but the cursor advances 0x20: the two pointers are not four bytes apart again
    assert g.variants(DRAFT.replace('var_t1 = var_t1_2 + 0x18', 'var_t1 = var_t1_2 + 0x10'), 'build') == []


def test_a_store_through_a_pointer_off_the_chain_is_left_alone():
    assert g.variants(DRAFT.replace('M2C_FIELD(var_t0_3, s32 *, 8) = var_a0_2;', 'M2C_FIELD(arg0, s32 *, 8) = var_a0_2;'), 'build') == []


def test_a_cursor_name_still_read_after_the_rewrite_leaves_the_function_alone():
    assert g.variants(DRAFT.replace('var_t4 += 1;', 'var_t4 += var_t1;'), 'build') == []


def test_the_module_declares_itself_to_the_registry():
    assert g.REPAIR['families'] == ('gbi_loop_cursor', 'gbi_loop_cursor_invariants')


# the same draft with m2c's names for what the loop pass hoisted (`temp_s1`, `sp14`): the second child writes them back
HOISTED = DRAFT.replace('    s32 *sp4;\n', '    s32 *sp4;\n    u32 temp_s1;\n    u32 sp14;\n').replace(
    '    temp_t7 = (arg5 & 7) << 0x15;\n', '    temp_t7 = (arg5 & 7) << 0x15;\n    temp_s1 = arg4 - 1;\n    sp14 = (u32) arg3 >> 1;\n').replace(
    '(((arg3 - 1) & 0xFFF) | 0xFD080000)', '(((sp14 - 1) & 0xFFF) | 0xFD080000)').replace(
    '    var_t4 += 1;\n', '    if (temp_s1 < var_t4) {\n                var_t4 = temp_s1;\n            }\n            var_t4 += 1;\n')


def test_the_loop_invariants_m2c_named_are_written_back_in_a_second_child():
    found = dict(g.variants(HOISTED, 'build'))
    assert set(found) == {'gbi_loop_cursor', 'gbi_loop_cursor_invariants'}
    plain, both = found['gbi_loop_cursor'], found['gbi_loop_cursor_invariants']
    assert 'temp_s1 = arg4 - 1;' in plain and 'sp14 = ' in plain
    assert 'temp_s1' not in both and 'sp14' not in both
    assert 'if ((arg4 - 1) < var_t4)' in both
    assert 'gDPSetTextureImage(gfx++, arg5, 1, ((u32) arg3 >> 1), arg1);' in both


def test_a_signed_cast_that_belongs_to_a_shifted_operand_is_kept_when_the_mask_is_dropped():
    """`(s32) (x + 8) >> 3` is an arithmetic shift of a signed sum. The field's `& 0x1FF` is the macro's own mask, but the
    cast sits inside the field: dropping it made the shift logical on an unsigned sum (`sra` became `srl`, 855 -> 655 once
    the cast was back on a 315-instruction tile builder). A cast on the whole field is still dropped."""
    draft = DRAFT.replace('temp_a0 = ((var_t4 >> 3) & 0x1FF) << 9;',
                          'temp_a0 = (((s32) (var_t4 + 8) >> 3) & 0x1FF) << 9;')
    body = _out(draft)
    assert 'gDPSetTile(gfx++, arg5, 1, (s32) (var_t4 + 8) >> 3, 0, 7, 0, 2, 0, 0, 2, 0, 0);' in body
