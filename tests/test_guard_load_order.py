from decomprepair.guard_load_order import FAMILY, variants

SOURCE = """static void *load(void **addr) { return *addr; }
extern int table;
void f(void *base) {
    f32 vector[3];
    void **slot;
    void *record;
    slot = slot_for(base);
    if (active() && ((vector[0] = *((f32 *) (((char *) load(slot)) + 0x34)),
        record = ((*((s8 *) (((char *) (*((void **) (((char *) base) + 0x68)))) + 0xE))) * 0xE8) + ((char *) (&table)),
        vector[2] = 0, vector[1] = *((f32 *) (((char *) (*slot)) + 0x38)), ready(record)))) {
        sink(vector);
    }
}"""
ROWS = [
    ('o', '', 'lwc1 $f0, 0x34($v0)'),
    ('r', 'lw $v1, 0x68($s7)', 'lw $v0, 0x68($s7)'),
    ('o', 'lwc1 $f0, 0x34($v0)', ''),
    ('r', 'lb $v1, 0xe($v1)', 'lb $v1, 0xe($v0)'),
]


def test_schedule_independent_guard_loads():
    [(family, candidate)] = variants(SOURCE, 'f', ROWS)
    assert family == FAMILY
    assert candidate.index('record =') < candidate.index('vector[0] =')
    assert candidate.index('vector[1] =') < candidate.index('vector[2] =')
    assert not variants(SOURCE, 'f', ROWS[:-1])
    assert not variants(SOURCE.replace('&& ((', '&& opaque((').replace('ready(record))))', 'ready(record)))'), 'f', ROWS)
    assert not variants(SOURCE.replace('return *addr;', 'log(); return *addr;'), 'f', ROWS)
    assert not variants(SOURCE.replace('slot = slot_for(base);', 'slot = slot_for(&record);'), 'f', ROWS)
    assert not variants(SOURCE, 'f', ROWS, '#define s8 volatile char')
