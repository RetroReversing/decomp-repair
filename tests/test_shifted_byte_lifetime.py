from decomprepair.shifted_byte_lifetime import variants

SOURCE = '''
void f(Voice *v, Note *n) {
    u32 pitch;
    u32 w;
    pitch = ((u32) (((u8 *) n)[2] * v->rate)) >> 7;
    pitch += ((u8 *) n)[1] << 16;
    w = n->word;
    use(pitch, w);
}
'''


def test_stages_byte_with_initialized_guard():
    result = variants(SOURCE, 'f')
    assert len(result) == 1
    family, child = result[0]
    assert family == 'shifted_byte_lifetime'
    assert 'u32 __repair_shifted_byte = ((u8 *) n)[1] << 16;' in child
    assert 'v->rate * ((u8 *) n)[2]' in child
    assert 'if (__repair_shifted_byte & 1) w = n->word;' in child
    assert 'else w = n->word;' in child


def test_refuses_unsafe_or_nonlocal_shapes():
    assert not variants(SOURCE.replace('<< 16', '<< 0'), 'f')
    assert not variants(SOURCE.replace('u32 w;', 'volatile u32 w;'), 'f')
    assert not variants(SOURCE.replace('use(pitch, w);', 'use(&w, pitch);'), 'f')
    assert not variants(SOURCE.replace('w = n->word;', 'w = read_word();'), 'f')


def test_unrelated_volatile_context_does_not_disable_the_family():
    assert variants(SOURCE, 'f', 'typedef volatile u32 vu32;')
    assert not variants(SOURCE, 'f', 'typedef volatile u32 Voice;')
