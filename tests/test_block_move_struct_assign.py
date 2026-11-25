"""m2c's GCC block-move expansion written back as one struct assignment (an 84-instruction routine, 9473 -> 0)."""
from decomprepair.block_move_struct_assign import FAMILY, variants

TESTED = """extern char gBuffer[];
extern char gCopy[];

s32 *save(void) {
    s32 *var_a0;
    s32 *var_v1;
    void *temp_v0;

    prepare(gBuffer);
    if (ready() != 0) {
        var_v1 = gCopy;
        var_a0 = gBuffer;
        temp_v0 = gBuffer + 0x210;
        if (((s32) &gBuffer | (s32) &gCopy) & 3) {
            do {
                M2C_FIELD(var_v1, s32 *, 0) = M2C_UNALIGNED32(M2C_FIELD(var_a0, s32 *, 0));
                M2C_FIELD(var_v1, s32 *, 4) = M2C_UNALIGNED32(M2C_FIELD(var_a0, s32 *, 4));
                M2C_FIELD(var_v1, s32 *, 8) = M2C_UNALIGNED32(M2C_FIELD(var_a0, s32 *, 8));
                M2C_FIELD(var_v1, s32 *, 0xC) = M2C_UNALIGNED32(M2C_FIELD(var_a0, s32 *, 0xC));
                var_a0 += 0x10;
                var_v1 += 0x10;
            } while (var_a0 != temp_v0);
        } else {
            do {
                M2C_FIELD(var_v1, s32 *, 0) = (s32) M2C_FIELD(var_a0, s32 *, 0);
                M2C_FIELD(var_v1, s32 *, 4) = (s32) M2C_FIELD(var_a0, s32 *, 4);
                M2C_FIELD(var_v1, s32 *, 8) = (s32) M2C_FIELD(var_a0, s32 *, 8);
                M2C_FIELD(var_v1, s32 *, 0xC) = (s32) M2C_FIELD(var_a0, s32 *, 0xC);
                var_a0 += 0x10;
                var_v1 += 0x10;
            } while (var_a0 != temp_v0);
        }
        M2C_FIELD(var_v1, s32 *, 0) = M2C_UNALIGNED32(M2C_FIELD(var_a0, s32 *, 0));
        M2C_FIELD(var_v1, s32 *, 4) = M2C_UNALIGNED32(M2C_FIELD(var_a0, s32 *, 4));
        M2C_FIELD(var_v1, s32 *, 8) = M2C_UNALIGNED32(M2C_FIELD(var_a0, s32 *, 8));
    }
    return gBuffer;
}
"""

ALIGNED = """void copy(void *arg0, void *arg1) {
    s32 *var_a2;
    s32 *var_a3;
    s32 *temp_t0;

    var_a2 = arg0 + 8;
    var_a3 = arg1;
    temp_t0 = arg1 + 0x20;
    do {
        M2C_FIELD(var_a2, s32 *, 0) = (s32) M2C_FIELD(var_a3, s32 *, 0);
        M2C_FIELD(var_a2, s32 *, 4) = (s32) M2C_FIELD(var_a3, s32 *, 4);
        M2C_FIELD(var_a2, s32 *, 8) = (s32) M2C_FIELD(var_a3, s32 *, 8);
        M2C_FIELD(var_a2, s32 *, 0xC) = (s32) M2C_FIELD(var_a3, s32 *, 0xC);
        var_a3 += 0x10;
        var_a2 += 0x10;
    } while (var_a3 != temp_t0);
    M2C_FIELD(var_a2, s32 *, 0) = (s32) M2C_FIELD(var_a3, s32 *, 0);
    M2C_FIELD(var_a2, s16 *, 4) = (s16) M2C_FIELD(var_a3, s16 *, 4);
    use(arg0);
}
"""


def children(source, name):
    found = variants(source, name)
    assert found and all(family == FAMILY for family, _ in found)
    return [text for _, text in found]


def test_tested_copy_becomes_one_byte_record_assignment():
    first = children(TESTED, 'save')[0]
    assert 'typedef struct { u8 data[0x21C]; } __repair_block21C;' in first
    assert '        *(__repair_block21C *)(gCopy) = *(__repair_block21C *)(gBuffer);\n    }' in first
    assert 'do {' not in first and 'M2C_UNALIGNED32' not in first
    for gone in ('var_a0', 'var_v1', 'temp_v0'):
        assert gone not in first
    assert first.index('typedef struct') < first.index('s32 *save(void)')


def test_tested_copy_also_offers_the_word_record():
    texts = children(TESTED, 'save')
    assert len(texts) == 2
    assert 'typedef struct { s32 data[0x87]; } __repair_block21Cw;' in texts[1]


def test_aligned_loop_with_a_halfword_tail():
    texts = children(ALIGNED, 'copy')
    # 0x20 bytes in the loop, then a word and a halfword: 0x26 bytes, not a whole number of words
    assert len(texts) == 1
    text = texts[0]
    assert 'typedef struct { u8 data[0x26]; } __repair_block26;' in text
    assert '    *(__repair_block26 *)(arg0 + 8) = *(__repair_block26 *)(arg1);\n' in text
    assert 'var_a2' not in text and 'var_a3' not in text and 'temp_t0' not in text


def test_a_pointer_used_after_the_copy_declines():
    assert variants(ALIGNED.replace('use(arg0);', 'use(var_a2);'), 'copy') == []


def test_word_record_first_without_the_alignment_test():
    source = ALIGNED.replace(
        "    M2C_FIELD(var_a2, s16 *, 4) = (s16) M2C_FIELD(var_a3, s16 *, 4);\n", "")
    texts = children(source, 'copy')
    assert 'typedef struct { s32 data[0x9]; } __repair_block24w;' in texts[0]
    assert 'u8 data[0x24]' in texts[1]


def test_other_code_is_left_alone():
    source = ALIGNED.replace('var_a3 += 0x10;', 'var_a3 += 0x8;')
    assert variants(source, 'copy') == []
    assert variants('void f(void) {\n    g = 1;\n}\n', 'f') == []
