"""counter_derived_offset on m2c's own spelling of a table walk: a `do { } while` loop with both steps at its end."""
from decomprepair import counter_derived_offset

M2C = """\
extern s32 D_80100000[];
void use(s32);

void func_80001000(s32 arg0) {
    s32 var_s0;
    s32 var_s1;

    if (arg0 > 0) {
        var_s0 = 0;
        var_s1 = 0;
        do {
            use(*(s32 *)((s8 *)D_80100000 + var_s1));
            var_s0 += 1;
            var_s1 += 4;
        } while (var_s0 < arg0);
    }
}
"""


def test_the_m2c_do_while_walk_reads_the_counter():
    found = counter_derived_offset.variants(M2C, 'func_80001000')
    texts = [text for family, text in found if family == 'counter_derived_offset']
    assert texts
    first = texts[0]
    assert 'use(*(s32 *)((s8 *)D_80100000 + (var_s0 << 2)));' in first
    assert 'var_s1 = 0;' not in first and 'var_s1 += 4;' not in first
    assert '            var_s0 += 1;\n        } while (var_s0 < arg0);' in first
    assert any('(var_s0 * 4)' in text for text in texts)


def test_a_differently_typed_counter_is_cast_to_the_offsets_type():
    source = M2C.replace('    s32 var_s0;', '    u32 var_s0;').replace('(var_s0 < arg0)', '(var_s0 < (u32) arg0)')
    first = counter_derived_offset.variants(source, 'func_80001000')[0][1]
    assert '((s32) (var_s0 << 2))' in first


def test_the_offset_steps_first_too():
    source = M2C.replace('            var_s0 += 1;\n            var_s1 += 4;\n', '            var_s1 += 4;\n            var_s0 += 1;\n')
    assert counter_derived_offset.variants(source, 'func_80001000')


def test_declines_when_the_offset_is_read_after_the_loop_or_starts_elsewhere():
    later = M2C.replace('        } while (var_s0 < arg0);\n', '        } while (var_s0 < arg0);\n        use(var_s1);\n')
    assert counter_derived_offset.variants(later, 'func_80001000') == []
    nonzero = M2C.replace('var_s1 = 0;', 'var_s1 = 8;')
    assert counter_derived_offset.variants(nonzero, 'func_80001000') == []
    # set inside a block that closes before the loop: not every path starts at 0
    closed = M2C.replace('        var_s1 = 0;\n', '').replace('    if (arg0 > 0) {', '    if (arg0 > 5) {\n        var_s1 = 0;\n    }\n    if (arg0 > 0) {')
    assert counter_derived_offset.variants(closed, 'func_80001000') == []
    narrow = M2C.replace('    s32 var_s0;', '    u16 var_s0;')
    assert counter_derived_offset.variants(narrow, 'func_80001000') == []
    skipped = M2C.replace('            use(', '            if (arg0 == 3) continue;\n            use(')
    assert counter_derived_offset.variants(skipped, 'func_80001000') == []
