"""A local initialised before a label that a goto enters past it, set at the label; the byte index widened first."""
from decomprepair import label_entry_initializer_repairs as m

SOURCE = '''extern u8 D_800F2720;

void f(s32 arg0, void *arg1, void *arg2) {
    u8 var_v0;
    u8 temp_a3;

    temp_a3 = M2C_FIELD(arg2, u8 *, 0x63);
    var_v0 = M2C_FIELD(arg1, u8 *, 0x63);
    if (((arg0 + 0x80) & 0xFF) < 2U) {
        goto pair_entry;
    }
    if ((u8)(arg0 + 0x7C) < 2) {
        u8 *base = &D_800F2720;
        s32 dst;
        s32 src;
        pair_entry: dst = var_v0 * 0x86;
        src = (temp_a3 & 0xFF) * 0x86;
        base[dst + (arg0 & 0xFE)] = base[src + (arg0 & 0xFE)];
        return;
    }
}
'''


def test_initialiser_moves_after_the_label_then_the_index_is_widened():
    out = [child for family, child in m.variants(SOURCE, 'f') if family == 'label_entry_initializer']
    assert len(out) == 2
    moved, widened = out
    assert 'u8 *base;' in moved and 'u8 *base = &D_800F2720;' not in moved
    assert 'pair_entry: base = &D_800F2720;\n        dst = var_v0 * 0x86;' in moved
    assert 'pair_entry: var_v0_wide = var_v0;\n        base = &D_800F2720;\n        dst = var_v0_wide * 0x86;' in widened
    assert widened.count('int var_v0_wide;') == 1 and widened.index('int var_v0_wide;') < widened.index('u8 *base;')


def test_left_alone_without_an_outside_goto_or_when_the_value_is_used_early():
    assert m.variants(SOURCE.replace('goto pair_entry;', 'return;'), 'f') == []
    assert m.variants(SOURCE.replace('        s32 src;\n', '        s32 src;\n        src = base[0];\n'), 'f') == []
    # a call is not a simple initialiser
    assert m.variants(SOURCE.replace('&D_800F2720', 'get()'), 'f') == []


def test_label_on_its_own_line_and_a_wide_index_already_there():
    source = SOURCE.replace('pair_entry: dst', 'pair_entry:\n        dst')
    moved = m.variants(source, 'f')[0][1]
    assert 'pair_entry: base = &D_800F2720;\n        dst = var_v0 * 0x86;' in moved or 'pair_entry:\n        base = &D_800F2720;' in moved
    assert m.variants(SOURCE.replace('u8 var_v0;', 's32 var_v0;'), 'f')[0][1].count('_wide') == 0
