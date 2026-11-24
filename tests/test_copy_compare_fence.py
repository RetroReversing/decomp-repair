"""copy_compare_fence: a copy before a compare of its source, fenced, with the compare as a flag before the branch.

Synthetic shape of an effect spawner's fade-in clamp (KMC GCC 2.7.2): the level's copy, a clamp below zero of the
other byte, then the bound test on the level. The measured child is the fence plus the flag before the last statement."""
from decomprepair import copy_compare_fence as c

SOURCE = '''void fade(u32 *obj)
{
    s32 word;
    s32 level;
    s32 out;
    s32 hi;
    s32 mask;
    s32 res;
    word = obj[4];
    level = (word & 0xFF) + 4;
    out = level;
    hi = (word >> 24) - 4;
    mask = (~hi) >> 31; res = hi & mask;
    if (level >= 0x100)
    {
        out = 0xFF;
    }
    obj[4] = out | (res << 24);
}
'''


def test_the_fence_and_the_flag_before_the_last_statement_are_children():
    found = c.variants(SOURCE, 'fade')
    assert found and {family for family, _ in found} == {c.FAMILY}
    texts = [text for _, text in found]
    assert any('do { out = level; } while (0);' in t and 'if (level >= 0x100)' in t for t in texts)
    want = 'mask = (~hi) >> 31; cmpFlag = level < 0x100; res = hi & mask;'
    match = [t for t in texts if want in t]
    assert match and 'if (!cmpFlag)' in match[0] and 's32 cmpFlag;' in match[0]
    assert 'do { out = level; } while (0);' in match[0]


def test_a_write_or_a_call_between_the_copy_and_the_compare_is_left_alone():
    assert c.variants(SOURCE.replace('hi = (word >> 24) - 4;', 'level = level + 1;'), 'fade') == []
    assert c.variants(SOURCE.replace('hi = (word >> 24) - 4;', 'hi = helper(word);'), 'fade') == []
    assert c.variants(SOURCE.replace('if (level >= 0x100)', 'if (level >= limit)'), 'fade') == []
