from decomprepair import returned_gfx_loop

SOURCE = '''extern s32 D_count;
extern s32 *D_table;

void *f(void *arg0) {
    char *var_t0;
    void *temp_a1;
    void *var_a2;
    void *var_a3;
    s32 var_v0;

    temp_a1 = arg0 + 8;
    var_a2 = temp_a1 + 8;
    var_a3 = var_a2 - 4;
    var_v0 = 0;
    var_t0 = D_table;
    M2C_FIELD(temp_a1, s32 *, 4) = 0x222;
    M2C_FIELD(arg0, s32 *, 0) = 0xE7000000;
    M2C_FIELD(temp_a1, s32 *, 0) = 0x111;
    M2C_FIELD(arg0, s32 *, 4) = 0;
loop_1:
    if (var_v0 < D_count) {
        if (*(s32 *)var_t0 != 0) {
            var_a3 += 8;
            var_a2 += 8;
            M2C_FIELD(var_a3, s32 *, -4) = (s32) (*(s32 *)var_t0 | 0x5000000);
            M2C_FIELD(var_a3, s32 *, 0) = 0;
        }
        var_v0 += 1;
        var_t0 += 4;
        goto loop_1;
    }
    M2C_FIELD(var_a2, s32 *, 0) = 0xE7000000;
    M2C_FIELD(var_a2, s32 *, 4) = 0;
    return var_a2 + 8;
}
'''


def test_loop_commands_go_back_to_one_advancing_cursor():
    children = dict(returned_gfx_loop.variants(SOURCE, 'f'))
    assert list(children) == ['returned_gfx_loop', 'returned_gfx_loop_else_break']
    text = children['returned_gfx_loop']
    assert 'M2C_FIELD' not in text.split('void *f(')[1]
    assert not any(gone in text for gone in ('temp_a1', 'var_a2', 'var_a3'))
    assert text.count('RepairGfxWords *_g = (RepairGfxWords *)arg0;') == 4
    assert text.index('_g->w0 = 0xE7000000;') < text.index('_g->w0 = 0x111;') < text.index('loop_1:')
    assert text.index('loop_1:') < text.index('_g->w0 = (s32) (*(s32 *)var_t0 | 0x5000000);')
    assert 'return arg0;' in text
    assert text.index('RepairGfxWords;') < text.index('void *f(')
    looped = children['returned_gfx_loop_else_break']
    assert 'loop_1' not in looped and 'break;' in looped


def test_declines_what_it_cannot_account_for():
    # a command the loop steps over with one word never written
    assert returned_gfx_loop.variants(SOURCE.replace('M2C_FIELD(var_a3, s32 *, 0) = 0;', ''), 'f') == []
    # the two pointers stepped apart
    assert returned_gfx_loop.variants(SOURCE.replace('var_a2 += 8;', 'var_a2 += 0x10;'), 'f') == []
    # another read of a pointer the rewrite would remove
    assert returned_gfx_loop.variants(SOURCE.replace('var_t0 += 4;', 'var_t0 += 4;\n        D_count = var_a2;'), 'f') == []
    # a value that calls would be moved by the address order
    assert returned_gfx_loop.variants(SOURCE.replace('= 0x111;', '= g();'), 'f') == []
