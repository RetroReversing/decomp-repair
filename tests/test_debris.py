"""What the permuter's bugs left in saved C, taken out."""
from decomprepair import debris

SOURCE = '''void f(void) {
    if (g()) {
        register D_80102ED4 = 0;
    }
    (*(s32 *)((char *)((unsigned short)D_80109698) + 0xFC)) = 1;
    (*(s32 *)(((unsigned)char *)(D_80109698) + 0x100)) = 2;
    v = (s32)w;
}
'''


def test_each_kind_goes():
    out = debris.clean(SOURCE)
    assert '        D_80102ED4 = 0;' in out
    assert '(*(s32 *)((char *)(D_80109698) + 0xFC)) = 1;' in out
    assert '(*(s32 *)((char *)(D_80109698) + 0x100)) = 2;' in out
    assert 'v = (s32)w;' in out  # an ordinary cast stays


def test_nothing_to_take_out():
    assert debris.clean('void f(void) {\n    register s32 v = 0;\n    p = (u8 *)(q) + 1;\n}\n') is None
    assert debris.clean(None) is None


def test_a_narrowed_hex_literal_loses_its_cast():
    from decomprepair import debris
    source = 'void f(u32 *p) {\n    p[0] = (unsigned short)0xDA380003;\n    p[1] = (u16)0x8000;\n}\n'
    out = debris.clean(source)
    assert 'p[0] = 0xDA380003;' in out and 'p[1] = (u16)0x8000;' in out


def test_a_16_bit_cast_on_a_variable_in_arithmetic_goes():
    from decomprepair import debris
    out = debris.clean('void f(s32 *p) {\n    s32 v;\n\n    v = (unsigned short)p[0];\n    p[1] = (unsigned short)v | 1;\n}\n')
    assert 'p[1] = v | 1;' in out
    assert 'v = (unsigned short)p[0];' in out  # (not an operand of arithmetic: left alone)
    assert debris.clean('s16 f(s32 x) {\n    return (s16)x + 1;\n}\n') is None  # (m2c's own spelling)


def test_do_while_zero_wrappers_go():
    from decomprepair import debris
    source = 'void f(void) {\n    /*__repair_loop_weight*/do {\n    v = g();} while (0);\n    h(v);\n}\n'
    out = debris.clean(source)
    assert 'while (0)' not in out and '__repair_' not in out and 'v = g();' in out
    # (a break inside binds to the wrapper: left alone)
    kept = 'void f(void) {\n    for (;;) {\n        do {\n            if (g()) break;\n        } while (0);\n    }\n}\n'
    assert debris.clean(kept) is None
    # (a break inside its own loop is fine)
    inner = 'void f(void) {\n    do {\n        while (g()) { break; }\n    } while (0);\n}\n'
    assert 'while (0)' not in debris.clean(inner)


def test_rows_goto_loops_become_do_while():
    from decomprepair import debris
    source = ('s32 f(s16 *p) {\n    s32 n;\n\n    n = 1;\n    __repair_rows: {\n        p += 3;\n        n += 1;\n    }\n'
              'if (*p == 0xE) goto __repair_rows;\n    return n;\n}\n')
    out = debris.clean(source)
    assert 'goto' not in out and 'do {' in out and '} while (*p == 0xE);' in out
    zero = source.replace('if (*p == 0xE) goto', 'if (0) goto')
    assert 'goto' not in debris.clean(zero) and 'while' not in debris.clean(zero)
    # (another goto to the label: left alone)
    assert '__repair_rows' in (debris.clean(source.replace('    return n;', '    goto __repair_rows;\n    return n;'))
                               or source)


def test_a_literal_local_becomes_the_literal():
    from decomprepair import debris
    source = 'u8 f(s32 i) {\nint __repair_literal;\n\n    __repair_literal = 0x10;\n    return D[i * __repair_literal];\n}\n'
    out = debris.clean(source)
    assert '__repair_literal' not in out and 'return D[i * 0x10];' in out
    # (assigned again elsewhere: left alone)
    twice = source.replace('    return', '    __repair_literal = g();\n    return')
    assert debris.clean(twice) is None


def test_a_single_use_temporary_is_written_back():
    from decomprepair import debris
    source = ('s32 f(s32 i, s32 *p) {\nchar *__repair_addr;\n\n    __repair_addr = (char *)((i * 0x28) + p);\n'
              '    if (*(s32 *)(__repair_addr) == 3) {\n        return 1;\n    }\n    return 0;\n}\n')
    out = debris.clean(source)
    assert '__repair_addr' not in out and 'if (*(s32 *)(((char *)((char *)((i * 0x28) + p)))) == 3)' in out
    # (a store between them could change what it reads: left alone)
    stored = source.replace('    if (', '    *p = 0;\n    if (')
    assert debris.clean(stored) is None
    # (read twice: left alone)
    twice = source.replace('return 1;', 'return *(s32 *)(__repair_addr);')
    assert debris.clean(twice) is None


def test_the_phase_union_becomes_a_pointer():
    from decomprepair import debris
    source = ('s32 f(s32 i, char *t) {\n    union { void * pointer; s32 value; } __repair_phase_storage;\n\n'
              '    __repair_phase_storage.pointer = (i * 2) + t;\n'
              '    return *(u8 *)((char *)(__repair_phase_storage.pointer) + 1);\n}\n')
    out = debris.clean(source)
    assert 'union' not in out and 'void *__repair_phase_pointer;' in out
    assert '__repair_phase_pointer = (i * 2) + t;' in out


def test_value_blocks_inline_helpers_and_cached_pointers_go_back():
    from decomprepair import debris
    source = '''void *__repair_cached_pointer = D_800CA31C;
static __inline__ int __repair_inline(s32 a, s32 b) { return a < b; }
void f(s32 n) {
    s32 var_s0;
    s32 var_a1;

    var_s0 = n;
    var_a1 = 0;
    do {
        var_a1 += 1;
    } while (__repair_inline(var_a1, 3));
    { s32 __repair_value; __repair_value = var_s0 * 8; var_s0 = __repair_value; }
    g(*(s32 *)((char *)(__repair_cached_pointer) + 4), var_s0);
}
'''
    out = debris.clean(source)
    assert '__repair' not in out
    assert '} while ((var_a1 < 3));' in out
    assert '    var_s0 = var_s0 * 8;' in out
    assert 'g(*(s32 *)((char *)(D_800CA31C) + 4), var_s0);' in out


def test_left_alone_where_meaning_could_change():
    from decomprepair import debris
    # the target has another type: the copy converts
    assert debris.clean('void f(void) {\n    u8 x;\n    { s32 __repair_value; __repair_value = g(); x = __repair_value; }\n}\n') is None
    # an argument with a call: evaluated once in the helper, maybe twice inline
    helper = 'static __inline__ int __repair_inline(s32 a, s32 b) { return a < a + b; }\nvoid f(void) {\n    h(__repair_inline(g(), 3));\n}\n'
    assert debris.clean(helper) is None
    # the cached symbol is assigned later in the file: the copy holds the old value
    cached = 'void *__repair_cached_pointer = D;\nvoid f(void) {\n    D = 0;\n    g(__repair_cached_pointer);\n}\n'
    assert debris.clean(cached) is None
