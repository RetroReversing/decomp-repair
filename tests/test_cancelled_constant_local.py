from decomprepair import cancelled_constant_local as repair

SOURCE = '''void f(u8 value) {
    s32 local;
    u8 byte;
    local = 224;
    byte = value;
    switch (value) {
    case 1:
        consume((byte & 0xff) + (local - 224));
        break;
    }
}
'''


def test_removes_only_the_cancelled_top_level_constant():
    out = repair.variants(SOURCE, 'f')
    assert len(out) == 1
    assert 'local' not in out[0][1]
    assert 'consume((byte & 0xff));' in out[0][1]


def test_requires_identical_constant_top_level_assignment_and_no_other_uses():
    assert not repair.variants(SOURCE.replace('local - 224', 'local - 223'), 'f')
    assert not repair.variants(SOURCE.replace('    local = 224;', '    if (value) { local = 224; }'), 'f')
    assert not repair.variants(SOURCE.replace('    byte = value;', '    use(local);\n    byte = value;'), 'f')
    assert not repair.variants(SOURCE.replace('u8 byte;', 'volatile u8 byte;'), 'f')


def test_rejects_volatile_typedefs_and_type_macros():
    assert not repair.variants(SOURCE, 'f', 'typedef volatile int s32;')
    assert not repair.variants(SOURCE, 'f', '#define u8 volatile char')
