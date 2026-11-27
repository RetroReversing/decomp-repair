"""endian_word_load on a made-up loader in m2c's shape (no game's code)."""
from decomprepair.endian_word_load import BASE, BOTH, REUSE, SPELL, WHOLE, variants
from decomprepair.registry import declared

SWAP_S = '((((word & 0xFF) << 8) + ((u32) (word & 0xFF00) >> 8)) << 0x10) + (((top & 0xFF) << 8) + (top >> 8))'
SWAP_A = '((((at & 0xFF) << 8) + ((u32) (at & 0xFF00) >> 8)) << 0x10) + (((top_2 & 0xFF) << 8) + (top_2 >> 8))'

DRAFT = f'''extern s32 D_80001000;
extern s32 D_80001004;
extern M2C_UNK D_80002000;
extern M2C_UNK D_B0001000;

s32 load(u8 *arg0) {{
    s32 out;
    s32 size;
    s32 buffer;
    s32 buffer_2;
    u32 at;
    u32 word;
    u32 top;
    u32 top_2;
    void *from;
    void *entry;

    buffer = ((u32) (D_80001000 + 0xF) >> 4) * 0x10;
    read(0, (s32) &D_B0001000, buffer);
    read(1, (s32) &D_B0001000, buffer);
    entry = find(buffer, arg0);
    if (entry != NULL) {{
        word = M2C_FIELD(entry, u32 *, 0x24);
        at = M2C_FIELD(entry, u32 *, 0x20);
        buffer_2 = ((u32) (D_80001004 + 0xF) >> 4) * 0x10;
        top = word >> 0x10;
        size = ((u32) ({SWAP_S} + 0xF) >> 4) * 0x10;
        top_2 = at >> 0x10;
        from = {SWAP_A} + &D_B0001000;
        read(2, (s32) from, buffer_2, size);
        out = ((u32) (&D_80002000 + 0xF) >> 4) * 0x10;
        unpack(buffer_2, out);
        return out;
    }}
    return 0;
}}
'''


def _children(source):
    return dict(variants(source, 'load'))


def test_whole_child_writes_every_step():
    child = _children(DRAFT)[WHOLE]
    assert 'repair_base = (s32) &D_B0001000;' in child
    assert 'buffer = D_80001000;\n    buffer = ((u32) (buffer + 0xF) >> 4) * 0x10;' in child
    assert 'if (entry == NULL) {' in child
    # the second buffer is the first one, set above the record's reads
    assert 'buffer_2' not in child
    assert child.index('buffer = D_80001004;') < child.index('word = M2C_FIELD')
    assert 'word = ((u32) (word + 0xF) >> 4) << 4;' in child
    assert '(((word >> 0x10) & 0xFF00) >> 8)' in child and ' top' not in child
    assert 'repair_base += at;' in child
    assert 'read(2, repair_base, buffer, word);' in child
    assert 'out = (s32) &D_80002000;\n' in child


def test_the_word_steps_come_apart_too():
    children = _children(DRAFT)
    assert {BOTH, SPELL, BASE} <= set(children)
    assert 'buffer_2' in children[BOTH]
    assert REUSE not in children  # it needs the buffers split first
    assert REUSE in _children(children[BOTH])


def test_a_signed_high_half_is_left_alone():
    assert SPELL not in _children(DRAFT.replace('u32 word;', 's32 word;').replace('u32 at;', 's32 at;'))


def test_a_loop_is_refused():
    assert not variants(DRAFT.replace('    entry = find', '    while (D_80001000) {}\n    entry = find'), 'load')


def test_registered():
    assert any(repair.module == 'endian_word_load' for repair in declared())
