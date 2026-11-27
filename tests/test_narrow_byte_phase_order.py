from decomprepair.narrow_byte_phase_order import variants

SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
s32 pan(void *, void *);
void f(void *p, u8 byte, int pitch) {
    s32 scratch;
    u8 channel;
    u8 phase;
    s32 bend;
    channel = byte & 0xF;
    scratch = pan(p, p);
    use(scratch & 0xFF);
    phase = (channel & 0xFF);
    scratch = phase * 0x10;
    bend = ((pitch + (byte << 7)) - 0x2000); bend = M2C_FIELD((scratch + M2C_FIELD(p, s32 *, 0x60)), s16 *, 4) * bend;
    M2C_FIELD((scratch + M2C_FIELD(p, s32 *, 0x60)), f32 *, 0xC) = 1.0f;
}
'''


def test_bounded_phase_is_narrowed_and_calculation_moved():
    out = variants(SOURCE, 'f')
    assert len(out) == 1
    text = out[0][1]
    assert 'u8 scratch;' in text
    assert text.index('bend = ((pitch') < text.index('phase = (channel')


def test_rejects_unbounded_or_other_uses():
    for text in (SOURCE.replace('byte & 0xF', 'byte & 0xFF', 1),
                 SOURCE.replace('use(scratch & 0xFF);', 'use(scratch);'),
                 SOURCE.replace('phase * 0x10', 'phase * 0x20'),
                 SOURCE.replace('pan(p, p);', 'pan(p, p); use(&scratch);'),
                 SOURCE.replace('s32 pan(', 'f32 pan(')):
        assert not variants(text, 'f')
