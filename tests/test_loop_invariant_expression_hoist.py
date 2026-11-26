from decomprepair.loop_invariant_expression_hoist import BOTH, HOIST, UNWRAP, variants

SOURCE = """#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern void *head;

void walk(void *arg0) {
    s16 temp;
    void *node;

    do { node = head; } while (0);
    if (node != NULL) {
        do {
            temp = M2C_FIELD(node, const s16 *, 8);
            if (temp == (s16) (M2C_FIELD(arg0, const u16 *, 0x216) + 0x64)) {
                M2C_FIELD(node, s16 *, 8) = (s16) (temp - 0x64);
            }
            do { node = M2C_FIELD(node, void **, 0xC); } while (0);
        } while (node != NULL);
    }
}
"""


def _by_family(source=SOURCE, name='walk'):
    out = {}
    for family, text in variants(source, name):
        out.setdefault(family, []).append(text)
    return out


def test_the_key_is_set_once_before_the_guard_and_the_fences_are_gone():
    texts = _by_family()[BOTH]
    want = [t for t in texts if t.index('key = (s16)') < t.index('node = head;')]
    assert want
    text = want[0]
    assert 's16 key;' in text
    assert 'temp == key' in text
    assert 'while (0)' not in text
    assert text.count('M2C_FIELD(arg0') == 1


def test_the_hoist_alone_keeps_the_fences():
    for text in _by_family()[HOIST]:
        assert 'while (0)' in text and 'temp == key' in text


def test_fences_unwrap_alone_in_loops_and_everywhere():
    texts = _by_family()[UNWRAP]
    assert any('do { node = head; } while (0);' in t and 'do { node = M2C' not in t for t in texts)
    assert any('while (0)' not in t for t in texts)


def test_an_expression_the_loop_assigns_is_not_hoisted():
    source = SOURCE.replace('(M2C_FIELD(arg0, const u16 *, 0x216) + 0x64)', '(M2C_FIELD(node, const u16 *, 0x216) + 0x64)')
    assert HOIST not in _by_family(source)


def test_a_memory_read_is_not_hoisted_out_of_a_loop_with_a_call():
    source = SOURCE.replace('M2C_FIELD(node, s16 *, 8) = (s16) (temp - 0x64);', 'g(node);')
    assert HOIST not in _by_family(source)


def test_a_fence_that_is_an_if_arm_is_kept():
    source = 'void f(int a) {\n    s32 b;\n    if (a) do { b = 1; } while (0);\n}\n'
    assert UNWRAP not in _by_family(source, 'f')
