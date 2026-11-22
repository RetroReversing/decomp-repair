"""store_temp_inline: a local read only by the store on the next line, written into that store.

Synthetic shape of the sequencer function's table lookup: `t = (i * 8) + *(u8 **)(base + 4);` and a word stored
through `(k * 4) + base` from three reads at `t`."""
from decomprepair import store_temp_inline as s

SOURCE = '''void fetch(u8 *base, s32 i, s32 k)
{
    void *t;
    s32 other;
    other = k + 1;
    t = (i * 8) + (*(u8 **)((char *)(base) + 4));
    (*(s32 *)((char *)(((k * 4) + base)) + 0xF80)) = (s32) (((*(u16 *)((char *)(t) + 0)) << 0x10) | ((*(u8 *)((char *)(t) + 2)) << 8) | (*(u8 *)((char *)(t) + 3)));
    base[other] = 1;
}
'''


def test_the_temp_is_written_into_the_store_that_reads_it():
    found = s.variants(SOURCE, 'fetch')
    assert [family for family, _ in found] == [s.FAMILY]
    text = found[0][1]
    assert 'void *t;' not in text and 't = ' not in text
    assert text.count('((void *)((i * 8) + (*(u8 **)((char *)(base) + 4))))') == 3
    assert 'other = k + 1;' in text


def test_a_temp_used_elsewhere_a_call_or_one_read_is_left_alone():
    assert s.variants(SOURCE.replace('base[other] = 1;', 'base[other] = (s32) t;'), 'fetch') == []
    assert s.variants(SOURCE.replace('(i * 8) +', 'helper(i) +'), 'fetch') == []
    one = SOURCE.replace(' | ((*(u8 *)((char *)(t) + 2)) << 8) | (*(u8 *)((char *)(t) + 3))', '')
    assert s.variants(one, 'fetch') == []
