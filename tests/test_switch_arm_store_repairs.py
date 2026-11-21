"""Store in each switch arm: the m2c form (one local, one store after the switch) becomes a store per arm."""
from decomprepair import switch_arm_store_repairs as h

PRELUDE = '''typedef int s32;
typedef unsigned char u8;
typedef unsigned short u16;
extern s32 reader(void *, s32);
extern u8 mode[];
extern const u16 *volatile G;
extern s32 H, K;
extern void table(void);
'''
# the shape the game's code had: the switch is the last statement of a bare block, and the store follows the block
SOURCE = PRELUDE + '''
void f(void) {
    const u16 *v;
    s32 n;

    n = reader(mode, 1);
    {
        u8 *m = mode;
        m[0] = reader(mode, 4);
        switch (m[0]) {
        case 5:
        case 6:
            v = (const u16 *)((const u8 *)table + 0x1C4);
            break;
        case 2:
            v = (const u16 *)((const u8 *)table + 0x198);
            break;
        default:
            v = (const u16 *)((const u8 *)table + 0x180);
            break;
        }
    }
    G = v;
    H = reader(mode, 8);
}
'''


def only(source=SOURCE, name='f'):
    got = h.variants(source, name)
    assert len(got) <= 1
    return got[0][1] if got else None


def test_each_arm_stores_and_the_store_after_the_switch_goes():
    text = only()
    assert h.variants(SOURCE, 'f')[0][0] == h.FAMILY
    assert text.count('G = (const u16 *)((const u8 *)table + 0x') == 3
    assert 'G = v;' not in text and 'v = (' not in text
    assert '        case 5:\n        case 6:\n            G = (const u16 *)((const u8 *)table + 0x1C4);\n            break;' in text
    assert '            G = (const u16 *)((const u8 *)table + 0x180);\n            break;\n        }\n    }\n    H = reader' in text
    assert text.count('\n') == SOURCE.count('\n')-1  # only the store's own line is gone
    assert '    const u16 *v;\n' in text  # (the now unused declaration is left alone)


def test_the_store_may_follow_the_switch_directly():
    plain = PRELUDE + 'void f(s32 x) {\n    s32 v;\n    switch (x) {\n    case 1:\n        v = 3;\n        break;\n    default:\n        v = 4;\n        break;\n    }\n    K = v;\n}\n'
    text = only(plain)
    assert 'K = 3;' in text and 'K = 4;' in text and 'K = v;' not in text


def test_an_arm_may_do_other_work_before_its_assignment():
    work = SOURCE.replace('        case 2:\n            v =', '        case 2:\n            H = 1;\n            v =')
    text = only(work)
    assert text and '            H = 1;\n            G = (const u16 *)((const u8 *)table + 0x198);' in text


def test_refused_when_the_local_is_used_anywhere_else():
    assert only(SOURCE.replace('    H = reader(mode, 8);', '    H = (s32)v;')) is None  # read after the store
    assert only(SOURCE.replace('    n = reader(mode, 1);', '    v = 0;\n    n = reader(mode, 1);')) is None  # set before
    assert only(SOURCE.replace('    G = v;', '    G = v;\n    v = 0;')) is None


def test_refused_when_an_arm_lacks_the_assignment_or_does_not_break():
    assert only(SOURCE.replace('        case 2:\n            v = (const u16 *)((const u8 *)table + 0x198);', '        case 2:\n            H = 2;')) is None
    assert only(SOURCE.replace('            break;\n        default:', '        default:')) is None  # falls through
    assert only(SOURCE.replace('        default:\n            v = (const u16 *)((const u8 *)table + 0x180);\n            break;\n',
                               '        default:\n            v = (const u16 *)((const u8 *)table + 0x180);\n')) is None  # no last break
    two = SOURCE.replace('    s32 n;\n', '    s32 n;\n    const u16 *w;\n').replace(
        'case 2:\n            v =', 'case 2:\n            w =').replace('v = (const u16 *)((const u8 *)table + 0x198)', 'w = (const u16 *)((const u8 *)table + 0x198)')
    assert only(two) is None  # the arms assign different variables


def test_refused_when_a_statement_runs_between_the_switch_and_the_store():
    assert only(SOURCE.replace('    G = v;\n    H = reader(mode, 8);', '    H = reader(mode, 8);\n    G = v;')) is None
    assert only(SOURCE.replace('    }\n    G = v;', '    }\n    if (n) {\n    }\n    G = v;')) is None
    # an `if` or loop body that ends right after the switch is not a bare block: the store sits outside it
    guarded = SOURCE.replace('    {\n        u8 *m = mode;', '    if (n) {\n        u8 *m = mode;')
    assert only(guarded) is None


def test_refused_when_an_arm_reads_the_global_or_has_an_effect_or_the_name_is_local():
    assert only(SOURCE.replace('(const u8 *)table + 0x198', '(const u8 *)G + 0x198')) is None
    assert only(SOURCE.replace('(const u8 *)table + 0x198', '(const u8 *)reader(mode, 1) + 0x198')) is None
    assert only(SOURCE.replace('(const u8 *)table + 0x198', '(const u8 *)(n++) + 0x198')) is None
    assert only(SOURCE.replace('    s32 n;\n', '    s32 n;\n    const u16 *volatile G;\n')) is None  # a local G, not the global


def test_nothing_for_a_missing_function_inline_assembly_or_no_switch():
    assert h.variants(SOURCE, 'missing') == []
    assert h.variants(SOURCE.replace('    n = reader', '    __asm__("nop");\n    n = reader'), 'f') == []
    assert h.variants(PRELUDE + 'void f(void) {\n    s32 v;\n    v = 1;\n    K = v;\n}\n', 'f') == []
