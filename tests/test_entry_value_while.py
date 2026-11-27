"""m2c's entry-value copy of a loop, written back as the while (a proximity scan over records and points, 450 -> 0)."""
from decomprepair import registry
from decomprepair.allocation_weight_combination import variants as weights
from decomprepair.entry_value_while import FAMILY, variants

SOURCE = """void walk(void) {
    f32 temp;
    f32 var;
    s32 off;
    void *p;
    s32 i;
    for (i = 0; i < 7; i++) {
        p = points;
        temp = M2C_FIELD(p, f32 *, 4);
        var = temp;
        if (temp != 0.0f) {
            off = i * 0x8F0;
            do {
                if (var < 26.0f) {
                    hit(off + base);
                }
                p += 0x10;
                var = M2C_FIELD(p, f32 *, 4);
            } while (var != 0.0f);
        }
    }
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'walk', '') if family == FAMILY]


def test_the_guard_and_do_become_a_while_reading_the_value_where_used():
    kept, inlined = children()
    assert 'while (M2C_FIELD(p, f32 *, 4) != 0.0f)' in kept and 'do' not in kept
    assert 'if (M2C_FIELD(p, f32 *, 4) < 26.0f)' in kept and 'off = i * 0x8F0;' in kept
    assert 'hit((i * 0x8F0) + base);' in inlined and 'off = i' not in inlined
    assert 'var = ' not in kept and 'temp = ' not in kept


def test_a_value_used_after_the_loop_keeps_the_guard():
    assert not children(SOURCE.replace('        }\n    }\n}\n', '        }\n        use(var);\n    }\n}\n'))


def test_a_use_after_a_call_or_the_step_keeps_the_guard():
    assert not children(SOURCE.replace('if (var < 26.0f) {', 'clear(); if (var < 26.0f) {'))
    assert not children(SOURCE.replace('p += 0x10;\n', 'p += 0x10;\n                use(var);\n'))


def test_a_different_reload_is_another_loop():
    assert not children(SOURCE.replace('var = M2C_FIELD(p, f32 *, 4);\n            } while', 'var = M2C_FIELD(p, f32 *, 8);\n            } while'))


def test_it_declares_itself():
    assert any(FAMILY in r.families for r in registry.declared())


def test_a_stepped_cursor_is_not_collapsed_into_its_base():
    source = """void walk(void) {
    u8 *base;
    u8 *cursor;
    s32 i;
    base = table;
    for (i = 0; i < 7; i++) {
        cursor = base;
        while (*cursor != 0) {
            cursor += 16;
        }
    }
}
"""
    assert not [t for f, t in weights(source, 'walk') if f == 'spill_slot_copy_collapse']
