from decomprepair import global_post_increment_split as repair

SOURCE = '''extern u16 sIndex;
extern u32 sBuffer[];
void record(u32 word) {
    s32 local = 0;
    if (sIndex < 0x400) {
        sBuffer[sIndex++] = word;
    }
    sBuffer[local++] = word;
    if (word) sBuffer[sIndex++] = word;
    ring->items[ring->head++] = word;
    sBuffer[sIndex++] = sIndex;
}
'''


def test_splits_global_and_member_indexes_only():
    out = [text for _, text in repair.variants(SOURCE, 'record')]
    every = out[-1]
    assert 'sBuffer[sIndex] = word;\n        sIndex++;' in every
    assert 'ring->items[ring->head] = word;\n    ring->head++;' in every
    assert 'sBuffer[local++] = word;' in every  # a local counter is increment_expression_repairs' work
    assert 'if (word) sBuffer[sIndex++] = word;' in every
    assert 'sBuffer[sIndex++] = sIndex;' in every
    assert len(out) == 3
