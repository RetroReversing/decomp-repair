"""debug_assembler_layout: the line layout a legacy `-g` MIPS build's assembler reads (a jump's slot, a hazard nop)."""
from decomprepair import debug_assembler_layout as m
from decomprepair import registry

DEBUG = ('-G0', '-mips3', '-O2', '-g3')

SOURCE = '''void f(s32 *p, s32 k, s32 s) {
    s32 a;
    s32 c;
    s32 v = p[0];
    a = v >> 6;
    if (v > 0) {
        c = k;
    } else {
        c = -k;
    }
    if (a > 10) a = 10;
    if (c < 0) {
        s32 d = (c >> 10) * s;
        p[1] = d - a;
    } else {
        p[1] = a;
    }
}
'''

MATCHED = '''void f(s32 *p, s32 k, s32 s) {
    s32 a;
    s32 c;
    s32 v = p[0];
    if (v > 0) {
        c = k; } else {
        c = -k;
    }
    a = v >> 6;
    if (a > 10) a = 10;
    if (c < 0) {
        s32 d_operand = c >> 10;
        s32 d = d_operand * s;
        p[1] = d - a;
    } else {
        p[1] = a;
    }
}
'''


def test_the_combination_comes_first_and_is_the_measured_layout():
    out = m.variants(SOURCE, 'f', DEBUG, arch='mips')
    assert out[0] == ('debug_assembler_layout', MATCHED)


def test_each_edit_alone_is_offered_too():
    out = dict((text, family) for family, text in m.variants(SOURCE, 'f', DEBUG, arch='mips'))
    alone = SOURCE.replace('        s32 d = (c >> 10) * s;\n',
                           '        s32 d_operand = c >> 10;\n        s32 d = d_operand * s;\n')
    assert out.get(alone) == 'debug_operand_line'
    assert any(f == 'debug_else_jump_layout' and 'c = k; } else {' in t for t, f in out.items())


def test_needs_a_debug_build_on_mips():
    assert m.variants(SOURCE, 'f', ('-O2',), arch='mips') == []
    assert m.variants(SOURCE, 'f', ('-O2', '-g0'), arch='mips') == []
    assert m.variants(SOURCE, 'f', DEBUG, arch='x86') == []
    assert m.variants('#line 3 "a.c"\n'+SOURCE, 'f', DEBUG, arch='mips') == []


def test_the_sink_keeps_the_program():
    """An assignment the condition or an arm reads, or whose operands an arm writes, stays before the `if`."""
    reads = SOURCE.replace('c = -k;', 'c = -a;')
    writes = SOURCE.replace('c = -k;', 'c = -k; v = 0;')
    calls = SOURCE.replace('a = v >> 6;', 'a = g(v);')
    for text in (reads, writes, calls):
        assert all('a = v >> 6;\n    if (v > 0)' in t or 'a = g(v);\n    if (v > 0)' in t
                   for f, t in m.variants(text, 'f', DEBUG, arch='mips'))


def test_a_name_in_use_is_not_reused_for_the_operand():
    taken = SOURCE.replace('s32 c;', 's32 c;\n    s32 d_operand;')
    assert all(f != 'debug_operand_line' for f, _ in m.variants(taken, 'f', DEBUG, arch='mips'))


def test_declared_in_the_registry():
    repair = registry.get('debug_assembler_layout')
    assert repair and registry.problems(repair) == [] and repair.archs == ('mips',)
