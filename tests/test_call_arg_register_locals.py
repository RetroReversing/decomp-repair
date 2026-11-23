from decomprepair import registry
from decomprepair.call_arg_register_locals import FAMILY, variants

SOURCE = """
extern s32 (*callback)(f32, void *, void *, void *);

void walk(u8 *out, const u8 *a, const u8 *b, f32 t, s32 n) {
    s32 temp_a0;
    s32 temp_a1;
    s32 temp_a2;
    s32 temp_a3;
    s32 var_a3;
    s32 i;
    s32 word;

    i = 0;
    do {
        word = *(s32 *)(a + i);
        temp_a1 = word >> 22;
        temp_a2 = word >> 10;
        temp_a3 = word << 1;
        *(s32 *)(out + i) = temp_a1 + temp_a2 + temp_a3;
        i += 4;
    } while (i < n);
    i = 0;
    do {
        var_a3 = i + 2;
        i += 4;
        temp_a0 = var_a3 * 4;
        callback(t, a + temp_a0, b + temp_a0, out + temp_a0);
    } while (i < n);
}
"""


def test_carries_the_arguments_in_the_register_named_locals_and_shares_the_offset():
    [(family, revised)] = variants(SOURCE, 'walk')
    assert family == FAMILY
    assert 'var_a3 = var_a3 * 4;' in revised
    assert 'temp_a1 = (s32)(a + var_a3);' in revised and 'temp_a2 = (s32)(b + var_a3);' in revised
    assert 'callback(t, (void *)temp_a1, (void *)temp_a2, out + var_a3);' in revised
    assert 'temp_a3' not in revised and 'temp_a0' not in revised.split('do {')[2]
    assert variants(revised, 'walk') == []


def test_declines_when_the_scaled_value_is_used_elsewhere():
    assert variants(SOURCE.replace('    } while (i < n);\n}', '    } while (i < n);\n    i = temp_a0;\n}'), 'walk') == []


def test_declines_when_the_call_block_mentions_the_sibling():
    assert variants(SOURCE.replace('var_a3 = i + 2;', 'var_a3 = i + 2 + temp_a3;'), 'walk') == []


def test_declines_without_the_carrier_locals():
    assert variants(SOURCE.replace('    s32 temp_a1;\n', ''), 'walk') == []


def test_registry_declares_the_family():
    assert any(FAMILY in repair.families for repair in registry.declared())
