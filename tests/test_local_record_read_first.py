from decomprepair.local_record_read_first import variants

SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void f(void *p, int i) {
    struct { s16 priority; s16 bus; u8 pitch; } config;
    config.bus = 0; config.pitch = 0;
    config.priority = (s16) M2C_FIELD((i + M2C_FIELD(p, s32 *, 0x60)), u8 *, 8);
    use(&config);
}
'''


def test_reads_before_two_independent_initializations():
    out = variants(SOURCE, 'f')
    assert len(out) == 1
    text = out[0][1]
    assert text.index('config.priority =') < text.index('config.bus =') < text.index('config.pitch =')


def test_rejects_escaping_or_aliased_or_static_record():
    assert not variants(SOURCE.replace('    config.bus = 0;', '    use(&config);\n    config.bus = 0;'), 'f')
    assert not variants(SOURCE.replace('struct {', 'static struct {'), 'f')
    assert not variants(SOURCE.replace('config.pitch = 0;', 'config.bus = 0;'), 'f')
    assert not variants(SOURCE, 'f', 'typedef volatile int s16;')
