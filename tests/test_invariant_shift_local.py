from decomprepair import invariant_shift_local as r

SOURCE = '''void f(u32 *a, u32 *b, u32 bits, u32 n) {
    u32 i;
    u32 c;
    c = 1;
    do {
        u32 j = 0;
        do {
            a[j] = b[j] & ((1 << bits) - 1);
            j++;
        } while (j < n);
        c++;
    } while (c < 16);
}
'''


def test_mask_is_named_once_before_the_loop_it_is_invariant_in():
    found = r.variants(SOURCE, 'f')
    texts = [text for _, text in found if 'inv_mask' in text]
    assert len(texts) == 1
    text = texts[0]
    assert 'void f(u32 *a, u32 *b, u32 bits, u32 n) { u32 inv_mask = (1 << bits) - 1;' in text
    assert 'b[j] & inv_mask' in text and '(1 << bits) - 1);' not in text.split('inv_mask = ')[1].split(';', 1)[1]


def test_the_outermost_loop_that_never_assigns_the_operand_is_chosen():
    source = SOURCE.replace('a[j] = b[j] & ((1 << bits) - 1);', 'a[j] = b[j] & (1 << c);')
    found = r.variants(source, 'f')
    assert len(found) == 1
    text = found[0][1]
    # c changes in the outer loop, so the local belongs to the inner loop's own block
    assert 'u32 j = 0;' in text and text.index('inv_bit = 1 << c') > text.index('do {')
    assert 'a[j] = b[j] & inv_bit;' in text


def test_a_shift_operand_the_loop_assigns_is_left_alone():
    source = SOURCE.replace('j++;', 'j++; bits--;')
    assert not [1 for _, text in r.variants(source, 'f') if 'inv_mask' in text]


def test_an_operand_assigned_before_the_block_opens_the_loop_is_left_alone():
    source = SOURCE.replace('    c = 1;\n', '    c = 1;\n    bits = c;\n').replace('f(u32 *a, u32 *b, u32 bits, u32 n) {', 'f(u32 *a, u32 *b, u32 bits, u32 n) {')
    assert [1 for _, text in r.variants(source, 'f') if 'inv_mask' in text] == []
