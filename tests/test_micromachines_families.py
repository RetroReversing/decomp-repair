"""Four families born from hand matches of KMC GCC 2.7.2 (-O2) functions: synthetic C, no game data."""
import re

from decomprepair import (
    flag_table_byte_read,
    list_walk_ladder_unwrap,
    masked_copy_counter_merge,
    narrow_table_byte_offset,
)


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_a_narrow_extern_indexed_by_record_bytes_gets_the_byte_offset_cast():
    code = '''extern u16 tab_a;

s32 find(s32 arg0) {
    s32 i;

    i = 0;
    while ((s32) *(&tab_a + ((i & 0xFFFF) * 4)) < arg0) {
        i += 1;
    }
    return i;
}
'''
    out = narrow_table_byte_offset.variants(code, 'find')
    assert [f for f, _ in out] == ['narrow_table_byte_offset']
    assert '*(u16 *)((u8 *)&tab_a + ((i & 0xFFFF) << 2))' in squash(out[0][1])
    # a word symbol, or a scale no wider than the type, is left alone
    assert narrow_table_byte_offset.variants(code.replace('u16 tab_a', 's32 tab_a'), 'find') == []
    assert narrow_table_byte_offset.variants(code.replace('* 4', '* 2'), 'find') == []


MASKED = '''extern char a[];

void copy(void) {
    s32 temp;
    s32 var_a0;
    s32 var_v0;

    var_v0 = 0 & 0xFF;
    var_a0 = 0;
    do {
        temp = var_v0 * 4;
        a[temp] = 1;
        var_a0 += 1;
        var_v0 = var_a0 & 0xFF;
    } while (var_v0 != 4);
}
'''


def test_a_word_counter_and_its_masked_copy_become_one_byte_counter():
    out = masked_copy_counter_merge.variants(MASKED, 'copy')
    assert [f for f, _ in out] == ['masked_copy_counter_merge']
    text = squash(out[0][1])
    assert 'u8 var_v0;' in text and 'var_a0' not in text and 'var_v0 += 1;' in text
    # a word counter read elsewhere is not merged
    assert masked_copy_counter_merge.variants(MASKED.replace('a[temp] = 1;', 'a[temp] = var_a0;'), 'copy') == []


FLAGS = '''extern s32 flags;
void walk(s32 n) {
    s32 i;

    for (i = 0; i < n; i++) {
        if (*(s32 *)(flags + i) != 0) {
            g(i);
        }
    }
}
'''
LBU = '''glabel walk
/* 0 0 90420000 */  lbu        $v0, 0x0($v0)
'''


def test_a_word_flag_read_becomes_a_byte_read_only_when_the_target_loads_bytes():
    out = flag_table_byte_read.variants(FLAGS, 'walk', LBU)
    assert [f for f, _ in out] == ['flag_table_byte_read']
    assert '*(u8 *)(flags + i) != 0' in squash(out[0][1])
    assert flag_table_byte_read.variants(FLAGS, 'walk', LBU.replace('lbu', 'lw')) == []
    assert flag_table_byte_read.variants(FLAGS, 'walk', '') == []


LADDER = '''extern void *head;

void *find(s32 arg0) {
    void *__repair_entry_p;
    void *r;
    void *p;

    p = head;
    if (p != NULL) {
        r = NULL;
        do {
            { void *__fence_p; do { __fence_p = __repair_entry_p; } while (0); r = __fence_p; }
            __repair_entry_p = p;
            if (!(M2C_FIELD(p, u16 *, 0) != arg0))
                break;
            p = M2C_FIELD(p, M2C_UNK **, 8);
            r = NULL;
        } while (p != NULL);
    }
    return r;
}
'''


def test_an_m2c_fence_ladder_around_a_list_find_becomes_the_plain_walk():
    out = list_walk_ladder_unwrap.variants(LADDER, 'find')
    assert [f for f, _ in out] == ['list_walk_ladder_unwrap']
    text = squash(out[0][1])
    assert 'if (M2C_FIELD(p, u16 *, 0) == arg0) { return p; }' in text
    assert 'p = M2C_FIELD(p, M2C_UNK **, 8);' in text and text.rstrip().endswith('return NULL; }')
    assert '__fence' not in text
    assert list_walk_ladder_unwrap.variants(LADDER.replace('r = NULL;\n        } while', 'r = p;\n        } while'), 'find') == []

