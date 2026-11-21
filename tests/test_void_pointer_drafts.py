from decomprepair.void_pointer_drafts import rewrite


def test_void_pointer_draft_keeps_byte_offsets_and_typed_arithmetic():
    raw = """void f(const void *base, int *typed, void **slots) {
    const void *first;
    const void *second;
    first = base + 0x278;
    second = first - 8;
    *slots = second + 8;
    first += 4;
    typed = typed + 8;
    slots = slots + 8;
    /* second = first + 8; */
}
"""
    expected = raw.replace('= base +', '= (const unsigned char *) base +')
    expected = expected.replace('= first -', '= (const unsigned char *) first -')
    expected = expected.replace('= second +', '= (const unsigned char *) second +')
    expected = expected.replace('first +=', 'first = (const unsigned char *) first +')
    assert rewrite(raw, 'f') == expected
    assert rewrite(expected, 'f') is None
    assert rewrite(raw, 'other') is None
