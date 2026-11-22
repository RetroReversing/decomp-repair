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


SIMPLE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void *find(s32 key) {
    void *node;
    void *result;
    node = get_head();
    result = NULL;
    if (node != NULL) {
loop_1:
        result = node;
        if (M2C_FIELD(node, s32 *, 12) != key) {
            node = M2C_FIELD(node, void **, 4);
            result = NULL;
            if (node != NULL) {
                goto loop_1;
            }
        }
    }
    return result;
}
'''


def test_standalone_copy_before_field_test():
    [(family, candidate)] = s.variants(SIMPLE, 'find')
    assert family == 'goto_search_loop'
    assert 'while (node != NULL)' in candidate
    assert 'return node;' in candidate
    assert 'goto loop_1' not in candidate


def test_standalone_copy_requires_safe_field_operations():
    for source, header in [
        (SIMPLE.replace('void *node;', 'volatile void *node;'), ''),
        (SIMPLE.replace('result = node;', 'result = node; use(result);'), ''),
        (SIMPLE.replace('M2C_FIELD(node, s32 *, 12) != key', 'M2C_FIELD(node, s32 *, 12) != read_key()'), ''),
        (SIMPLE.replace('node = get_head();', 'node = get_head(); use(&result);'), ''),
        (SIMPLE, '#define HIDDEN result'),
        (SIMPLE, '#undef M2C_FIELD'),
        (SIMPLE.replace('(*(type_ptr)', '(effect(), *(type_ptr)'), ''),
    ]:
        assert s.variants(source, 'find', header) == []
