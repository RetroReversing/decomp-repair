"""An accumulator updated in both arms of an if/else, written as one update after the join."""
from decomprepair import arm_accumulate_join as x
from decomprepair import registry

SOURCE = '''s32 f(s32 arg0, s32 arg1) {
    s32 temp_v0;
    s32 var_a3;
    u8 var_v1;
    u8 temp_a2;

    var_v1 = 0;
    var_a3 = 0;
    if (arg0 > 0) {
        temp_a2 = M2C_FIELD(D_80096A0C, u8 *, 0x70);
        do {
            temp_v0 = var_v1 & 0xFF;
            if ((temp_a2 == 4) || (temp_a2 == 6)) {
                var_a3 += *(D_80100A8C + temp_v0);
            } else {
                var_a3 += *(D_80100A48 + temp_v0);
            }
            var_v1 += 1;
        } while ((var_v1 & 0xFF) < arg0);
    }
    return (var_a3 & 0xFF) + arg1;
}
'''


def test_one_update_after_the_join_and_the_widths_together():
    # SN64 GCC 2.8.1 -O1, a 29-instruction table sum: 30 -> 10 with the join, 0 with the widths and the init order.
    out = [text for family, text in x.variants(SOURCE, 'f')]
    assert {family for family, _ in x.variants(SOURCE, 'f')} == {'arm_accumulate_join'}
    joined = out[0]
    assert 'value = *(D_80100A8C + temp_v0);' in joined and 'value = *(D_80100A48 + temp_v0);' in joined
    assert '            }\n            var_a3 += value;\n            var_v1 += 1;' in joined
    assert '    s32 value;\n' in joined and joined.count('var_a3 +=') == 1
    exact = out[1]
    assert 'u8 var_a3;' in exact and 's32 var_v1;' in exact
    assert exact.index('var_a3 = 0;') < exact.index('var_v1 = 0;')
    assert 'u8 var_a3;' in out[2] and out[2].index('var_v1 = 0;') < out[2].index('var_a3 = 0;')


def test_left_alone_otherwise():
    other = SOURCE.replace('var_a3 += *(D_80100A48', 'var_v1 += *(D_80100A48')
    assert x.variants(other, 'f') == []
    # an accumulator read whole somewhere keeps its width: only the join
    whole = SOURCE.replace('return (var_a3 & 0xFF) + arg1;', 'return var_a3 + arg1;')
    assert len(x.variants(whole, 'f')) == 1


def test_declared():
    assert registry.get('arm_accumulate_join').families == ('arm_accumulate_join',)
