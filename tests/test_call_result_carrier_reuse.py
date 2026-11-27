"""A call's result written back into the variable its argument was computed from, through m2c's carrier local."""
from decomprepair import call_result_carrier_reuse as x
from decomprepair import registry

SOURCE = '''s16 f(s32, s32);                    /* extern */
extern s32 D;
void g(void *arg2) {
    s16 sp10[3];
    s16 temp_s3_2;
    s32 temp_s0;
    u32 temp_s3;
    s32 bias;

    temp_s3 = ((*(s16 *)((s8 *)arg2 + 0)) + (*(s16 *)((s8 *)arg2 + 4))) - D;
    bias = (s32) (temp_s3 + (temp_s3 >> 0x1F));
    temp_s0 = (s32) ((*(s16 *)((s8 *)arg2 + 2)) - D) / 2;
    temp_s3_2 = f(0x100, bias >> 1);
    sp10[0] = f(0x100, temp_s0);
    sp10[1] = -temp_s3_2;
    h(sp10);
}
'''


def test_the_result_goes_back_into_the_sum():
    # An N64 function (KMC GCC 2.7.2 -O1 -g): 80 -> 0 with the three edits together, 120 without the prototype.
    (family, merged), (_, widened) = x.variants(SOURCE, 'g')
    assert family == 'call_result_carrier_reuse'
    assert 'temp_s3_2' not in merged and 's32 temp_s3;' in merged
    assert 'bias = temp_s3 / 2;' in merged and 'temp_s3 = f(0x100, bias);' in merged
    assert 'sp10[1] = -temp_s3;' in merged and merged.startswith('s16 f(s32, s32);')
    assert widened.startswith('s32 f(s32, s32);') and widened.split('\n', 1)[1] == merged.split('\n', 1)[1]


def test_left_alone_otherwise():
    # the sum read again after the halving: it cannot take the result
    assert x.variants(SOURCE.replace('    h(sp10);', '    h(temp_s3);'), 'g') == []
    # the result assigned again
    assert x.variants(SOURCE.replace('    h(sp10);', '    temp_s3_2 = 1;'), 'g') == []


def test_declared():
    assert registry.get('call_result_carrier_reuse').families == ('call_result_carrier_reuse',)
