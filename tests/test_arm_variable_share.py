"""The same role in the two arms of an `if`/`else` written as one variable: counters and the index derived from them.

Synthetic shape of the 851-instruction ray test's mesh loops: a halfword index table and a byte index table, each walked
by its own counted loop with its own counter and its own derived index, in the two arms of one `if`."""
from decomprepair import arm_variable_share as s

SOURCE = '''s32 scan(u8 *mesh, s32 flag)
{
    s32 var_s0;
    s32 var_s0_2;
    s32 var_s5;
    s32 var_s5_2;
    u16 *wide;
    u8 *narrow;
    s32 best;
    best = -1;
    if (flag & 4) {
        wide = (u16 *)mesh;
        var_s0 = 0;
        do {
            var_s5 = var_s0 & 0xFFFF;
            if (wide[var_s5] > 3) {
                best = var_s5;
            }
        } while ((u16) ++var_s0 < 9);
    } else {
        narrow = mesh;
        var_s0_2 = 0;
        do {
            var_s5_2 = var_s0_2 & 0xFFFF;
            if (narrow[var_s5_2] > 3) {
                best = var_s5_2;
            }
        } while ((u16) ++var_s0_2 < 9);
    }
    return best;
}
'''


def _texts(source=SOURCE):
    found = s.variants(source, 'scan')
    assert all(family == s.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_counters_and_their_indices_are_shared_in_one_child():
    both = _texts()[0]
    assert 'var_s0_2' not in both and 'var_s5_2' not in both
    assert 'var_s0 = 0;' in both and both.count('var_s0 = 0;') == 2
    assert both.count('var_s5 = var_s0 & 0xFFFF;') == 2
    assert 'wide' in both and 'narrow' in both


def test_each_pair_is_also_offered_alone():
    texts = _texts()
    assert len(texts) == 3
    assert any('var_s0_2' not in t and 'var_s5_2' in t for t in texts)


def test_locals_used_outside_their_arm_are_not_shared():
    leaked = SOURCE.replace('    return best;', '    return best + var_s0_2;')
    assert all('var_s0_2' in t for t in _texts(leaked))


def test_a_pair_with_different_first_values_is_not_shared():
    other = SOURCE.replace('var_s0_2 = 0;', 'var_s0_2 = 1;')
    assert all('var_s0_2' in t for t in _texts(other))


def test_a_function_without_an_else_is_left_alone():
    flat = SOURCE.replace(' else {', ' } if (!(flag & 4)) {')
    assert s.variants(flat, 'scan') == []


def test_data_temporaries_with_the_same_first_value_stay_apart():
    temps = SOURCE.replace('    s32 best;', '    s32 best;\n    u16 flags_a;\n    u16 flags_b;')
    temps = temps.replace('            if (wide[var_s5] > 3) {', '            flags_a = wide[var_s5];\n            if (flags_a > 3) {')
    temps = temps.replace('            if (narrow[var_s5_2] > 3) {', '            flags_b = wide[var_s5_2];\n            if (flags_b > 3) {')
    assert all('flags_a' in t and 'flags_b' in t for t in _texts(temps))
