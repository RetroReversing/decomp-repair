"""m2c's goto tree of range tests with a shared tail, written as a `switch` with case ranges."""
from decomprepair import registry
from decomprepair.goto_tree_range_switch import FAMILY, variants

SOURCE = '''void draw(s32 *out, s32 v) {
    s32 r;
    s32 g;

    if (v < 0xA0) {
        if (v < 0x8C) {
            r = 0xC8;
            if (v < 0x78) {
                r = 0xFF;
                if (v >= 0) {
                    g = 0xFF;
                    goto join;
                }
                goto bad;
            }
            g = 0xC8;
            goto join;
        }
        r = 0xA0;
        g = 0xA0;
        goto join;
    }
    r = 0x50;
    if (v < 0x100) {
        g = 0;
join:
        if (!(flags & 1)) {
            g = 1;
        }
        *out = r | g;
        return;
    }
bad:
    report(v);
}
'''


def test_the_tree_becomes_a_switch_with_ranges_and_the_shared_tail_after_it():
    (family, text), = variants(SOURCE, 'draw')
    assert family == FAMILY
    assert 'goto' not in text and 'join:' not in text
    assert 'case 0 ... 0x77:\n        r = 0xFF;\n        g = 0xFF;\n        break;' in text
    assert 'case 0x78 ... 0x8B:\n        r = 0xC8;\n        g = 0xC8;' in text
    assert 'case 0xA0 ... 0xFF:\n        r = 0x50;\n        g = 0;' in text
    assert 'default:\n        report(v);\n        return;\n    }\n    if (!(flags & 1)) {' in text
    assert '    *out = r | g;\n}' in text
    assert text.count('{') == text.count('}')


def test_other_shapes_are_left_alone():
    assert variants(SOURCE.replace('void draw', 's32 draw'), 'draw') == []
    assert variants(SOURCE.replace('goto bad;', 'goto missing;'), 'draw') == []
    assert variants(SOURCE.replace('r = 0xA0;', 'while (r) { r--; }'), 'draw') == []


def test_the_module_declares_itself_to_the_registry():
    for repair in registry.declared():
        if repair.module == 'goto_tree_range_switch':
            assert registry.problems(repair) == []
            return
    raise AssertionError('not declared')
