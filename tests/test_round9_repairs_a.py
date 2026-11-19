"""Round nine: permuter casts on compared operands and int literals taken out, and m2c's compare tree read as a
`switch` when its leaves carry their constants through a variable."""
from decomprepair import compare_tree_switch_repairs as c
from decomprepair import debris


def test_a_16_bit_cast_on_a_compared_variable_goes():
    out = debris.clean('int f(u32 a) {\n    if ((unsigned short)a != 0x20) {\n        return 1;\n    }\n    return 0;\n}\n')
    assert 'if (a != 0x20)' in out


def test_an_int_cast_on_a_literal_that_fits_goes_and_one_that_doesnt_stays():
    out = debris.clean('int f(u32 a) {\n    if (a == (int)0x20) return 1;\n    if (a == (int)0x80000000) return 2;\n'
                       '    return (u16)a;\n}\n')
    assert 'a == 0x20' in out and '(int)0x80000000' in out and '(u16)a' in out


SOURCE = '''s32 f(u32 arg0) {
    s32 var_v0;

    if (arg0 != 0x20) {
        if (arg0 < 0x21U) {
            var_v0 = 4;
            if (arg0 != 0x10) {
                return 0;
            }
            /* Duplicate return node #9. Try simplifying control flow for better match */
            return var_v0;
        }
        if (arg0 != 0x40) {
            var_v0 = 7;
            if (arg0 != 0x80) {
                return 0;
            }
            return var_v0;
        }
        var_v0 = 6;
        return var_v0;
    }
    return 5;
}
'''


def test_carried_constants_read_as_direct_returns():
    # An N64 function at 18.6%: exact as the switch.
    texts = [t for _, t in c.variants(SOURCE, 'f')]
    assert texts and all('var_v0' not in t for t in texts)
    assert any('case 0x10:\n        return 4;' in t and 'case 0x80:\n        return 7;' in t and '    return 0;\n}' in t
               for t in texts)


def test_a_variable_with_other_uses_is_left_to_the_plain_reading():
    other = SOURCE.replace('    return 5;\n}', '    return var_v0 + 5;\n}')
    assert all('var_v0' in t for _, t in c.variants(other, 'f')) or c.variants(other, 'f') == []
