from decomprepair.compare_flag_arm_share import FAMILY, variants

SOURCE = """void func(Snd *o)
{
    s32 dist;
    s32 vol;
    s32 ch;

    dist = get();
    if (dist < o->range) {
        vol = ((o->range - dist) << 7) / o->range;
        ch = o->ch;
        o->vol = vol;
        if (D_800B2B60[ch] < vol) {
            o->vol = D_800B2B60[ch];
        }
        send(0x11, o);
    } else if (o->active != 0) {
        o->unk94 = -1;
        o->unk64 = o->unk70 * 100;
        send(0x11, o);
        o->active = 0;
    }
}
"""


def test_the_compare_and_the_other_arms_store_share_one_flag():
    [(family, revised)] = variants(SOURCE, 'func')
    assert family == FAMILY
    assert '{\n    int flag;\n    s32 dist;' in revised
    assert '        flag = D_800B2B60[ch] < vol;\n        if (flag) {' in revised
    assert '        flag = o->unk70 * 100;\n        o->unk64 = flag;' in revised
    # the literal store and the outer compare (whose arms are the two sides) are left alone
    assert 'o->unk94 = -1;' in revised and 'if (dist < o->range)' in revised


def test_no_else_arm_or_no_computed_store_offers_nothing():
    no_else = SOURCE[:SOURCE.index(' else if')] + '\n}\n'
    assert variants(no_else, 'func') == []
    assert variants(SOURCE.replace('o->unk70 * 100', 'o->unk70'), 'func') == []


def test_compares_with_calls_or_logic_are_skipped():
    assert variants(SOURCE.replace('D_800B2B60[ch] < vol', 'D_800B2B60[ch] < vol && ch'), 'func') == []
    assert variants(SOURCE.replace('D_800B2B60[ch] < vol', 'look(ch) < vol'), 'func') == []
