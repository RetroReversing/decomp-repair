from decomprepair.record_comma_order import variants

SOURCE = '''
void f(void *p) {
    struct { s16 a; u8 b; } cfg;
    if ((cfg.b = 0, cfg.a = (s16) (*(u8 *)p), ready())) { use(&cfg); }
}
'''


def test_swaps_unescaped_record_fields():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    assert 'cfg.a = (s16) (*(u8 *)p), cfg.b = 0' in children[0][1]


def test_rejects_possible_aliases_and_overlapping_storage():
    for changed in (SOURCE.replace('    if (', '    use(&cfg);\n    if ('),
                    SOURCE.replace('    if (', '    capture(cfg);\n    if ('),
                    SOURCE.replace('    if (', '    __asm__("");\n    if ('),
                    SOURCE.replace('s16 a;', 'volatile s16 a;'),
                    SOURCE.replace('struct {', 'static struct {'),
                    SOURCE.replace('struct {', 'volatile struct {'),
                    SOURCE.replace('s16 a;', 's16 a:4;'),
                    SOURCE.replace('struct {', 'union {'),
                    SOURCE.replace('    if (', '    union { s16 a; u8 b; } cfg;\n    if ('),
                    SOURCE.replace('    if (', '    Alias cfg;\n    if ('),
                    SOURCE.replace('cfg.a = (s16) (*(u8 *)p)', 'cfg.b = (s16) (*(u8 *)p)')):
        assert not variants(changed, 'f')
