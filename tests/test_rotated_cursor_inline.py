from decomprepair import registry
from decomprepair.rotated_cursor_inline import FAMILY, REPAIR, variants

SOURCE = """s32 claim_first(s32 limit, void *zone) {
    s32 var_s0;
    void *temp_v1;
    void *var_v0;

    var_s0 = 0;
    var_v0 = zone;
loop_1:
    if (M2C_FIELD(var_v0, s8 *, 0x60) != -1) {
        temp_v1 = zone + var_s0;
        if (limit < M2C_FIELD(temp_v1, s8 *, 0x67)) {
            return 1;
        }
    }
    var_s0 += 1;
    var_v0 = zone + var_s0;
    if (var_s0 >= 7) {
        return 0;
    }
    goto loop_1;
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'claim_first') if f == FAMILY]


def test_the_cursor_is_the_index_expression_where_it_is_read():
    got = children()
    assert len(got) == 1
    child = got[0]
    assert 'M2C_FIELD((zone + var_s0), s8 *, 0x60)' in child
    assert 'var_v0' not in child
    assert 'temp_v1 = zone + var_s0;' in child and 'var_s0 += 1;' in child


def test_a_cursor_that_is_not_the_index_is_left_alone():
    assert not children(SOURCE.replace('var_s0 = 0;', 'var_s0 = 1;'))
    assert not children(SOURCE.replace('var_v0 = zone;', 'var_v0 = zone;\n    zone = 0;'))
    # read after the counter's step: it still holds the previous element there
    assert not children(SOURCE.replace('var_s0 += 1;', 'var_s0 += 1;\n    limit = M2C_FIELD(var_v0, s8 *, 0);'))
    assert not children(SOURCE.replace('void *var_v0;', 's8 *var_v0;'))


def test_the_module_declares_itself():
    assert REPAIR['families'] == (FAMILY,)
    assert any(entry.module.endswith('rotated_cursor_inline') for entry in registry.declared())
