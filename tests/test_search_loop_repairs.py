"""m2c's goto form of a list search, as the while loop that returns what it finds."""
from decomprepair import search_loop_repairs as s

SOURCE = '''void *f(s32 arg0, s32 arg1, void *arg2) {
    u32 temp_v1;
    void *temp_v0;
    void *var_a2;
    void *var_v0;

    var_a2 = arg2;
    var_v0 = NULL;
    if (var_a2 != NULL) {
loop_1:
        temp_v0 = M2C_FIELD(var_a2, void **, 0x3C);
        if ((temp_v0 == NULL) || (temp_v1 = M2C_FIELD(temp_v0, u32 *, 0x30), (((temp_v1 >> 4) & 0xFFFF) != arg0)) || (var_v0 = var_a2, ((temp_v1 >> 0x14) != arg1))) {
            var_a2 = M2C_FIELD(var_a2, void **, 0x10);
            var_v0 = NULL;
            if (var_a2 != NULL) {
                goto loop_1;
            }
        }
    }
    return var_v0;
}
'''


def test_the_loop_returns_the_node():
    # An N64 function at 230: exact as this loop.
    (family, out), = s.variants(SOURCE, 'f')
    assert family == 'goto_search_loop'
    assert '''    while (var_a2 != NULL) {
        temp_v0 = M2C_FIELD(var_a2, void **, 0x3C);
        if (!((temp_v0 == NULL) || (temp_v1 = M2C_FIELD(temp_v0, u32 *, 0x30), (((temp_v1 >> 4) & 0xFFFF) != arg0)) || (((temp_v1 >> 0x14) != arg1)))) {
            return var_a2;
        }
        var_a2 = M2C_FIELD(var_a2, void **, 0x10);
    }
    return NULL;
}''' in out
    assert 'var_v0' not in out and 'goto' not in out


def test_left_alone_without_the_copy():
    assert s.variants(SOURCE.replace('(var_v0 = var_a2, ((temp_v1 >> 0x14) != arg1))', '((temp_v1 >> 0x14) != arg1)'), 'f') == []
