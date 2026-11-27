from decomprepair import global_read_head, registry

SOURCE = '''extern u16 sCounter;
void start(void *arg0) {
    s16 next;

    M2C_FIELD(arg0, s16 *, 0x10) = 0x100;
    M2C_FIELD(arg0, s8 *, 0x18) = 1;
    M2C_FIELD(arg0, s16 *, 0x12) = 0x100;
    M2C_FIELD(arg0, s8 *, 0x19) = 0;
    M2C_FIELD(arg0, s8 *, 0x1A) = 0x40;
    M2C_FIELD(arg0, s8 *, 0x1B) = 0x40;
    next = sCounter + 1;
    M2C_FIELD(arg0, s16 *, 0x1C) = next;
}
'''


def body(child):
    return [line.strip() for line in child.splitlines() if line.startswith('    ') and '=' in line]


def test_the_global_read_goes_to_the_head_of_the_run():
    children = global_read_head.variants(SOURCE, 'start')
    assert [family for family, _ in children] == ['global_read_head', 'global_read_head']
    assert body(children[0][1])[0] == 'next = sCounter + 1;'
    assert body(children[1][1])[:2] == ['M2C_FIELD(arg0, s16 *, 0x10) = 0x100;', 'next = sCounter + 1;']
    assert all(sorted(child.splitlines()) == sorted(SOURCE.splitlines()) for _, child in children)


def test_member_stores_are_passed_too():
    source = '''typedef struct { s16 a; s16 b; s16 c; s16 d; s16 e; s16 f; s16 g; } Rec;
extern u16 sCounter;
void start(void *arg0) {
    s16 next;

    ((Rec *) arg0)->a = 1;
    ((Rec *) arg0)->b = 1;
    ((Rec *) arg0)->c = 1;
    ((Rec *) arg0)->d = 1;
    ((Rec *) arg0)->e = 1;
    next = sCounter;
    ((Rec *) arg0)->f = next;
}
'''
    assert len(global_read_head.variants(source, 'start')) == 1


def test_nothing_is_passed_that_the_read_does_not_commute_with():
    call = SOURCE.replace('M2C_FIELD(arg0, s8 *, 0x19) = 0;', 'reset();')
    assert global_read_head.variants(call, 'start') == []
    written = SOURCE.replace('M2C_FIELD(arg0, s8 *, 0x19) = 0;', 'sCounter = 0;')
    assert global_read_head.variants(written, 'start') == []


def test_only_global_reads_far_enough_down_are_offered():
    local = SOURCE.replace('next = sCounter + 1;', 'next = 2;')
    assert global_read_head.variants(local, 'start') == []
    near = SOURCE.replace('    M2C_FIELD(arg0, s8 *, 0x1A) = 0x40;\n    M2C_FIELD(arg0, s8 *, 0x1B) = 0x40;\n', '')
    assert global_read_head.variants(near, 'start') == []


def test_the_registry_runs_it():
    assert any('global_read_head' in repair.families for repair in registry.declared())
