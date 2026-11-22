from decomprepair import scheduling_scope

SOURCE = """void f(void *record, int value) {
    if (value) {
        *((s16 *) (((char *) record) + 0x38)) = value;
        *((s16 *) (((char *) record) + 0x42)) = value + 1;
        *((u8 *) (((char *) record) + 0x3F)) = value;
    }
}"""


def test_wraps_halfword_between_stores_to_the_same_record():
    (_, candidate), = scheduling_scope.variants(SOURCE, 'f')
    middle = '*((s16 *) (((char *) record) + 0x42)) = value + 1;'
    assert f'do {{ {middle} }} while (0);' in candidate
    assert candidate.count(middle) == 1


def test_requires_same_record_and_mips():
    other = SOURCE.replace('(char *) record) + 0x3F', '(char *) other) + 0x3F')
    assert scheduling_scope.variants(other, 'f') == []
    assert scheduling_scope.variants(SOURCE, 'f', 'ppc') == []
