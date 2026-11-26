"""accumulate_separate_dest: `acc += f(x);` written into a separate destination so the call result stays first.

Synthetic shapes of two small N64 string-width loops (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): the target added
the call result first (`addu $s2,$v0,$s2`) and every spelling of the accumulate gave the accumulator first; the
temporary `temp_v0 = f(x) + acc; acc = temp_v0;`, declared right after the accumulator, matched (5 -> 0, 20 -> 15 -> 0)."""
from decomprepair import accumulate_separate_dest as s
from decomprepair import registry

SOURCE = '''s32 width(u8 *arg0, s32 arg1) {
    s32 var_s0;
    s32 var_s2;
    u8 *var_s1;
    u8 temp_a0;

    var_s1 = arg0;
    var_s0 = arg1;
    var_s2 = 0;
    do {
        temp_a0 = *var_s1;
        if (temp_a0 != 0) {
            var_s2 += glyph(temp_a0, 0);
        }
        var_s1 += 1;
    } while (var_s1 != 0);
    return var_s2 & 0xFFFF;
}
'''


def _texts(source=SOURCE, name='width'):
    return [text for family, text in s.variants(source, name) if family == s.FAMILY]


def test_the_call_result_goes_first_in_a_destination_of_its_own():
    first = _texts()[0]
    assert 'sep_var_s2 = glyph(temp_a0, 0) + var_s2; var_s2 = sep_var_s2;' in first
    assert 'var_s2 += glyph' not in first


def test_the_temporary_is_declared_right_after_the_accumulator():
    first = _texts()[0]
    assert '    s32 var_s2;\n    s32 sep_var_s2;\n    u8 *var_s1;' in first


def test_the_other_operand_order_and_the_late_declaration_are_offered():
    texts = _texts()
    assert any('sep_var_s2 = var_s2 + glyph(temp_a0, 0);' in t for t in texts)
    assert any('    u8 temp_a0;\n    s32 sep_var_s2;\n' in t for t in texts)


def test_the_assigned_forms_are_respelled_too():
    for form in ('var_s2 = var_s2 + glyph(temp_a0, 0);', 'var_s2 = glyph(temp_a0, 0) + var_s2;'):
        texts = _texts(SOURCE.replace('var_s2 += glyph(temp_a0, 0);', form))
        assert texts and 'sep_var_s2 = glyph(temp_a0, 0) + var_s2;' in texts[0]


def test_a_compound_with_a_sum_is_parenthesised():
    text = _texts(SOURCE.replace('var_s2 += glyph(temp_a0, 0);', 'var_s2 += temp_a0 - 1;'))[0]
    assert 'sep_var_s2 = (temp_a0 - 1) + var_s2;' in text


def test_a_bare_operand_only_for_the_assigned_forms():
    # `acc = acc * a + b` is `(acc * a) + b`, not `acc * (a + b)`
    assert not _texts(SOURCE.replace('var_s2 += glyph(temp_a0, 0);', 'var_s2 = var_s2 * temp_a0 + 1;'))


def test_subtraction_and_a_foreign_accumulator_are_left_alone():
    assert not _texts(SOURCE.replace('var_s2 += glyph(temp_a0, 0);', 'var_s2 -= glyph(temp_a0, 0);'))
    assert not _texts(SOURCE.replace('var_s2 += glyph(temp_a0, 0);', 'var_s2 += var_s2;'))
    assert not _texts(SOURCE.replace('var_s2 += glyph(temp_a0, 0);', 'var_s2 += temp_a0++;'))


def test_every_site_together_and_other_operators():
    source = SOURCE.replace('var_s2 += glyph(temp_a0, 0);', 'var_s2 += glyph(temp_a0, 0);\n            var_s0 |= temp_a0;')
    texts = _texts(source)
    both = [t for t in texts if 'sep_var_s2 = ' in t and 'sep_var_s01 = temp_a0 | var_s0;' in t]
    assert both and 'var_s0 |= temp_a0' not in both[0]


def test_it_declares_itself_to_the_registry():
    assert s.FAMILY in {f for item in registry.declared() for f in item.families}
    assert not registry.problems(registry.get('accumulate_separate_dest'))


SHIFTED = '''s16 width(u8 *arg0, s32 arg1) {
    s32 temp_a1;
    s32 var_a0;
    s32 var_v0;

    var_a0 = arg1;
    temp_a1 = var_a0;
    if (arg0 != NULL) {
        var_v0 = var_a0 << 0x10;
        if (*arg0 != 0) {
            var_a0 += temp_a1;
        }
    } else {
        var_v0 = var_a0 << 0x10;
    }
    return var_v0 >> 0x10;
}
'''


def test_the_shift_pair_return_becomes_the_cast_and_the_scratch_goes():
    from decomprepair import shift_pair_return_cast as r
    text = r.variants(SHIFTED, 'width')[0][1]
    assert 'return (s16) var_a0;' in text and 'var_v0' not in text


def test_the_accumulate_and_the_cast_are_offered_together():
    texts = _texts(SHIFTED)
    assert any('sep_var_a0 = temp_a1 + var_a0;' in t and 'return (s16) var_a0;' in t for t in texts)


def test_a_scratch_with_another_use_is_kept():
    from decomprepair import shift_pair_return_cast as r
    assert not r.variants(SHIFTED.replace('return var_v0 >> 0x10;', 'use(var_v0); return var_v0 >> 0x10;'), 'width')
