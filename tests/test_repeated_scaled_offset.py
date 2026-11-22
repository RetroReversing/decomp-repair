from decomprepair.scaled_size_inline_repairs import SCALED_OFFSET, variants

SOURCE = '''
typedef unsigned int u32;
void use(u32);
u32 f(u32 start) {
    u32 words[2];
    words[0] = start;
    use(start + (((words[0] >> 6) * 40) + 256));
    return start + (((words[0] >> 6) * 0x28) + 0x100);
}
'''


def helpers(source):
    return [text for family, text in variants(source, 'f') if family == SCALED_OFFSET]


def test_one_unsigned_helper_replaces_both_offsets():
    candidate, = helpers(SOURCE)
    assert 'static inline unsigned int repair_scaled_offset(unsigned int value)' in candidate
    assert 'return ((value >> 6) * 40U) + 256U;' in candidate
    assert candidate.count('repair_scaled_offset(words[0])') == 2


def test_requires_matching_unsigned_offsets():
    assert not helpers(SOURCE.replace('u32 words[2]', 'int words[2]'))
    assert not helpers(SOURCE.replace('>> 6) * 40', '>> 7) * 40'))


def test_rejects_shadowed_array():
    source = SOURCE.replace('    use(', '    { int words[2]; use(').replace(' + 256));', ' + 256)); }')
    assert not helpers(source)


def test_rejects_shadow_after_another_declarator():
    source = SOURCE.replace('    use(', '    { int zero = 0, words[2]; use(').replace(' + 256));', ' + 256)); }')
    assert not helpers(source)
