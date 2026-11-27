"""A byte offset added to a typed pointer, read back as bytes."""
from decomprepair import byte_offset_on_pointer as repair

SOURCE = '''void start(void *arg0, s32 index) {
    s32 offset;

    offset = index * 4;
    if (*(offset + M2C_FIELD(arg0, void ***, 0xC)) != 0) {
        gValue = *(offset + M2C_FIELD(arg0, s16 **, 0x10));
    }
}
'''


def child(source):
    out = repair.variants(source, 'start')
    return out[0][1] if out else None


def test_the_word_read_is_taken_as_bytes():
    out = child(SOURCE)
    assert '*(void * *)(offset + (s32)(M2C_FIELD(arg0, void ***, 0xC)))' in out
    # a halfword field with a word offset is not a double scale of this offset
    assert '*(offset + M2C_FIELD(arg0, s16 **, 0x10))' in out


def test_an_offset_that_is_not_a_multiple_of_the_element_is_left_alone():
    assert child(SOURCE.replace('index * 4', 'index')) is None
    assert child(SOURCE.replace('offset = index * 4;', 'offset = index * 4;\n    offset += 1;')) is None


def test_a_store_through_the_sum_is_left_alone():
    source = SOURCE.replace('gValue = *(offset + M2C_FIELD(arg0, s16 **, 0x10));',
                            '*(offset + M2C_FIELD(arg0, void ***, 0x10)) = 0;')
    assert '*(offset + M2C_FIELD(arg0, void ***, 0x10)) = 0;' in child(source)
