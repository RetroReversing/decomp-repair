"""A narrow local counted in an empty arm inside a loop: loop.c's insn count grows, flow deletes the counter."""
from decomprepair import dead_narrow_counter as d
from decomprepair import registry

SOURCE = '''void f(s32 arg0) {
    s16 *msg = NULL;

    G = 0;
    for (;;) {
        recv(&msg);
        switch (*msg) {
        case 1:
            if (M == 10) {
            } else if (M < 11) {
                switch (M) {
                case 0:
                    G++;
                    break;
                }
            }
            break;
        case 2:
            G--;
            break;
        }
    }
}
'''


def texts(source=SOURCE):
    return [t for _, t in d.variants(source, 'f')]


def test_the_empty_arm_in_the_loop_gets_each_counter_form():
    out = texts()
    assert len(out) == 3
    assert {fam for fam, _ in d.variants(SOURCE, 'f')} == {d.FAMILY}
    masked, plain, two = out
    assert '            if (M == 10) {\n                dead_count = (dead_count + 1) & 7;\n            } else' in masked
    assert '    u8 dead_count = 0;\n' in masked
    assert '                dead_count++;\n            } else' in plain
    assert '    u8 dead_count = 0, dead_count_b = 0;\n' in two
    assert 'dead_count++;\n                dead_count_b++;' in two


def test_the_counter_is_never_read():
    for text in texts():
        for line in text.split('\n'):
            if 'dead_count' in line:
                assert line.strip().startswith(('u8 dead_count', 'dead_count'))


def test_no_loop_or_no_empty_arm_gives_nothing():
    assert d.variants(SOURCE.replace('for (;;) {', '{'), 'f') == []
    assert d.variants(SOURCE.replace('if (M == 10) {\n            } else ', ''), 'f') == []
    # an empty initialiser is no arm
    assert d.variants('void f(void) {\n    for (;;) {\n        S s = {};\n        g(&s);\n    }\n}\n', 'f') == []


def test_a_name_in_use_is_not_reused():
    out = texts(SOURCE.replace('G = 0;', 'G = 0; dead_count();'))
    assert 'u8 dead_count2 = 0;' in out[0]


def test_it_declares_itself_to_the_registry():
    item = registry.get('dead_narrow_counter')
    assert item is not None and tuple(item.families) == (d.FAMILY,)
