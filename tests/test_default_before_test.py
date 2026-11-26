from decomprepair import default_before_test

SOURCE = '''void update(void)
{
    s32 flags;
    s32 mode;
    u8 *p;

    flags = read();
    p = &table;
    send(*p);
    if (flags & 0x10) {
        if (global & 0x1000) {
            mode = 0x3E;
        } else {
            mode = 0x3D;
            store = *(u16 *)(p - 4);
        }
        play(mode);
        flags = 0;
    }
    if (flags & 0x20) {
        play(0x3A);
    }
}
'''
EXPECTED = '''    do { } while (0);
    if (flags & 0x10) {
        flags = 0;
        mode = 0x3E;
        if (!(global & 0x1000)) {
            mode = 0x3D;
            store = *(u16 *)(p - 4);
        }
        play(mode);
    }
'''


def sources(source):
    return [child for _, child in default_before_test.variants(source, 'update')]


def squeeze(text):
    return [line.rstrip() for line in text.split('\n') if line.strip()]


def test_default_hoisted_store_and_fence_come_as_one_child():
    want = squeeze(EXPECTED)
    assert any(all(line in squeeze(child) for line in want)
               and '\n'.join(want) in '\n'.join(squeeze(child)) for child in sources(SOURCE))


def test_the_move_alone_is_also_offered():
    first = sources(SOURCE)[0]
    assert 'mode = 0x3E;\n        if (!(global & 0x1000)) {' in first and 'else' not in first
    assert 'do {' not in first


def test_declined_when_the_test_reads_the_local_or_the_arm_does_not_overwrite_it():
    assert not sources(SOURCE.replace('global & 0x1000', 'mode & 0x1000'))
    assert not sources(SOURCE.replace('            mode = 0x3D;\n', ''))


def test_a_store_the_block_reads_is_not_hoisted():
    out = sources(SOURCE.replace('play(mode);', 'play(mode + flags);'))
    assert out and not any('flags = 0;\n        mode' in child for child in out)
