"""m2c's character ladder (an 89-instruction N64 text converter): the four spellings and their combined child."""
from decomprepair import registry
from decomprepair.m2c_ladder_cleanup import BOUNDS, COMBINED, CURSOR, FALLBACK, GOTO_CASE, variants

SOURCE = '''s8 *convert(u8 *arg0, s32 arg1, s8 *arg2) {
    s32 var_t1;
    s8 *var_a3;
    u8 *var_a0;
    u8 temp_v1;

    var_a0 = arg0;
    var_t1 = 0;
    if (arg1 > 0) {
        var_a3 = arg2;
        do {
            temp_v1 = *var_a0;
            if (temp_v1 >= 0x42U) {
                goto block_3;
            }
            if ((u32) ((temp_v1 - 0x10) & 0xFF) < 0xAU) {
                *var_a3 = temp_v1 + 0x20;
            } else if ((temp_v1 != 0) || (var_t1 >= (arg1 - 1))) {
                switch (*var_a0) {
                case 0x38:
block_3:
                    *var_a3 = 0x2A;
                    break;
                case 0x0:
                    *var_a3 = 0;
                    break;
                }
            } else {
                *var_a3 = 0x20;
            }
            var_a3 += 1;
            var_t1 += 1;
            var_a0 += 1;
        } while (var_t1 < arg1);
    }
    return arg2;
}
'''


def _children(source=SOURCE):
    found = {}
    for family, text in variants(source, 'convert'):
        found.setdefault(family, []).append(' '.join(text.split()))
    return found


def test_an_early_goto_into_a_case_becomes_an_arm_with_the_case_body():
    text, = _children()[GOTO_CASE]
    assert 'if (temp_v1 >= 0x42U) { *var_a3 = 0x2A; } else if' in text
    assert 'goto' not in text and 'block_3' not in text


def test_pointers_stepped_beside_the_counter_become_indexes():
    text, = _children()[CURSOR]
    assert 'temp_v1 = arg0[var_t1];' in text and 'arg2[var_t1] = temp_v1 + 0x20;' in text
    assert 'var_a0' not in text and 'var_a3' not in text and 'var_t1 += 1;' in text


def test_a_pointer_used_after_its_loop_keeps_its_cursor():
    source = SOURCE.replace('    return arg2;', '    *var_a3 = 0;\n    return arg2;')
    assert 'var_a3 += 1;' in _children(source).get(CURSOR, ['var_a3 += 1;'])[0]


def test_the_masked_range_of_a_byte_is_two_bounds():
    text, = _children()[BOUNDS]
    assert 'if (temp_v1 >= 0x10 && temp_v1 <= 0x19) {' in text
    assert BOUNDS not in _children(SOURCE.replace('    u8 temp_v1;', '    s32 temp_v1;'))


def test_the_else_beside_a_switch_is_also_its_default():
    kept, turned = _children()[FALLBACK]
    assert 'default: *var_a3 = 0x20; break; } } else { *var_a3 = 0x20; }' in kept
    assert 'else if (!((temp_v1 != 0) || (var_t1 >= (arg1 - 1)))) { *var_a3 = 0x20; } else {' in turned
    assert 'default: *var_a3 = 0x20; break; } } var_a3 += 1;' in turned
    assert FALLBACK not in _children(SOURCE.replace('case 0x0:', 'default:'))


def test_a_switch_that_kept_its_default_still_takes_the_turned_round_if():
    kept = SOURCE.replace('*var_a3 = 0;\n                    break;\n', '*var_a3 = 0;\n                    break;\n'
                          '                default:\n                    *var_a3 = 0x20;\n                    break;\n')
    turned, = _children(kept)[FALLBACK]
    assert 'else if (!((temp_v1 != 0)' in turned and turned.count('default:') == 1


def test_the_combined_child_makes_all_four_at_once():
    family, text = variants(SOURCE, 'convert')[0]
    assert family == COMBINED
    assert 'goto' not in text and 'var_a0' not in text and 'default:' in text and '& 0xFF' not in text


def test_the_module_declares_itself():
    assert any('m2c_ladder_cleanup' in str(entry) for entry in registry.declared())
