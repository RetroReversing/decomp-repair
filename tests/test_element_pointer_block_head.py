"""The element a block's member stores share, taken as a pointer at the block's head."""
from decomprepair import element_pointer_block_head as m
from decomprepair import registry

SOURCE = '''void f(Tri *out, s32 *table, s32 n) {
    s32 i;
    s32 a;
    u16 count;

    count = 0;
    for (i = 0;; i++) {
        if (i >= n) {
            break;
        }
        a = table[i];
        out[count].x = a;
        out[count].y = a + 1;
        out[count].z = a + 2;
        count++;
    }
}
'''


def test_pointer_follows_the_exit_test():
    out = m.variants(SOURCE, 'f')
    assert [family for family, _ in out] == ['element_pointer_block_head']
    text = out[0][1]
    assert '    Tri *element;\n' in text
    assert '            break;\n        }\n        element = &out[count];\n        a = table[i];' in text
    assert 'element->x = a;\n        element->y = a + 1;\n        element->z = a + 2;\n        count++;' in text
    assert 'out[count]' not in text.replace('&out[count]', '')


def test_declines_what_would_move_the_element():
    for change in (SOURCE.replace('a = table[i];', 'a = table[i];\n        count++;'),
                   SOURCE.replace('a = table[i];', 'again:\n        a = table[i];'),
                   SOURCE.replace('a = table[i];', 'out = other();'),
                   SOURCE.replace('        out[count].z = a + 2;\n', ''),
                   SOURCE.replace('a = table[i];', 'g(&count);'),
                   SOURCE.replace('        out[count].y = a + 1;\n', '        if (a) out[count].y = a + 1;\n')):
        assert m.variants(change, 'f') == []


def test_registered():
    assert any(r.module == 'element_pointer_block_head' for r in registry.declared())
