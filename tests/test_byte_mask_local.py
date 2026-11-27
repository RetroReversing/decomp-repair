from decomprepair.byte_mask_local import variants

SOURCE = '''void f(int x) {
    s32 channel;
    channel = (x & 0xFF);
    use(channel * 16);
    if (x == channel) use(x);
}
'''


def test_narrows_masked_word():
    out = variants(SOURCE, 'f')
    assert len(out) == 1
    assert 'u8 channel;' in out[0][1]


def test_rejects_unsafe_uses():
    for text in (SOURCE.replace('use(channel * 16);', 'channel++;'),
                 SOURCE.replace('use(channel * 16);', 'use(&channel);'),
                 SOURCE.replace('use(channel * 16);', 'use(sizeof(channel));'),
                 SOURCE.replace('use(channel * 16);', 'use(channel);'),
                 SOURCE.replace('0xFF', '0x1FF'),
                 SOURCE.replace('use(channel * 16);', '{ int channel; use(channel); }')):
        assert not variants(text, 'f')
    assert not variants(SOURCE, 'f', '#define u8 volatile char')
