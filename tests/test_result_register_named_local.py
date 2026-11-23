from decomprepair import registry
from decomprepair.result_register_named_local import FAMILY, variants

SOURCE = """
void pack(u32 *out, const s32 *in, s32 n) {
    s32 temp_v0;
    s32 var_a3;
    s32 i;

    temp_v0 = n * 2;
    i = 0;
    do {
        var_a3 = in[i] & 0xFFE;
        var_a3 = in[i + 1] + var_a3;
        out[i] = (var_a3 & 0xFFE) >> 1;
        i += 1;
    } while (i < temp_v0);
    var_a3 = 0;
}
"""


def test_writes_the_sum_into_the_register_named_local():
    [(family, revised)] = variants(SOURCE, 'pack')
    assert family == FAMILY
    assert 'temp_v0 = in[i + 1] + var_a3;' in revised
    assert 'out[i] = (temp_v0 & 0xFFE) >> 1;' in revised
    assert variants(revised, 'pack') == []


def test_declines_when_the_sum_is_read_twice_or_the_local_is_in_the_block():
    assert variants(SOURCE.replace('i += 1;', 'i += var_a3;'), 'pack') == []
    assert variants(SOURCE.replace('i += 1;', 'i += temp_v0;'), 'pack') == []


def test_declines_when_the_variable_is_read_after_the_block():
    assert variants(SOURCE.replace('var_a3 = 0;', 'out[0] = var_a3;'), 'pack') == []


def test_registry_declares_the_family():
    assert any(FAMILY in repair.families for repair in registry.declared())
