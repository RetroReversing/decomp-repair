import re

from decomprepair import registry
from decomprepair.induction_reverse_reduction import FAMILIES, FAMILY, SWITCH_FAMILY, variants

# m2c's reading of a loop whose reduced variable (var_s1 = 0x50 + 10 * i) the delay-slot filler copied into three jumps
CHAIN = """
void menu(void *arg0) {
    s32 var_s0;
    s32 var_s1;
    s32 var_a0;
    s32 var_a0_2;
    u32 guard_value;

    guard_value = (D_limit > 0);
    var_s1 = 0x50;
    var_s0 = 0;
    if (guard_value) {
        do {
            draw(0xA0, var_s1);
            var_a0 = 0x77;
            if (var_s0 == M2C_FIELD(arg0, s32 *, 0x88)) {
                var_a0 = 0xFF;
            }
            tint(var_a0, var_a0);
            if (var_s0 != 1) {
                if (var_s0 < 2) {
                    var_a0_2 = 0xA4;
                    if (var_s0 != 0) {
                        var_s1 += 0xA;
                    } else {
                        goto block_11;
                    }
                } else {
                    var_a0_2 = 0xA7;
                    if (var_s0 != 2) {
                        var_s1 += 0xA;
                    } else {
                        goto block_11;
                    }
                }
            } else {
                var_a0_2 = 0xA6;
block_11:
                var_s1 += 0xA;
                shown(var_a0_2);
            }
            var_s0 += 1;
        } while (var_s0 < D_limit);
    }
    done(0xA2);
}
"""

FOR = """    for (var_s0 = 0; var_s0 < D_limit; var_s0++) {
        draw(0xA0, var_s0 * 10 + 0x50);
        var_a0 = 0x77;
        if (var_s0 == M2C_FIELD(arg0, s32 *, 0x88)) {
            var_a0 = 0xFF;
        }
        tint(var_a0, var_a0);
        switch (var_s0) {
            case 0: shown(0xA4); break;
            case 1: shown(0xA6); break;
            case 2: shown(0xA7); break;
        }
    }
"""

PLAIN = """
void walk(s32 *out) {
    s32 i;
    s32 off;
    i = 0;
    off = 0x20;
    if (D_count > 0) {
        do {
            put(i, off);
            off += 8;
            i += 1;
        } while (i < D_count);
    }
}
"""


def names(source):
    return [family for family, _ in variants(source, 'menu')]


def test_declared():
    assert set(FAMILIES) == {FAMILY, SWITCH_FAMILY}
    assert {repair.module for repair in registry.declared()} >= {'induction_reverse_reduction'}


def test_chain_becomes_the_for_loop_with_a_switch():
    children = dict.fromkeys(text for _, text in variants(CHAIN, 'menu'))
    assert FOR in next(iter(children))
    assert 'guard_value = ' not in next(iter(children))
    assert 'var_s1 +=' not in next(iter(children))
    assert len(children) <= 8


def test_reduction_alone_keeps_the_do_loop_and_the_gotos():
    kept = [text for _, text in variants(CHAIN, 'menu') if 'goto block_11' in text]
    assert kept
    assert all('var_s1' not in re.sub(r'(?m)^\s*s32 var_s1;\n', '', text) for text in kept)
    assert any('do {' in text and 'draw(0xA0, var_s0 * 10 + 0x50);' in text for text in kept)
    assert any('for (var_s0 = 0;' in text and 'goto block_11' in text for _, text in variants(CHAIN, 'menu'))


def test_plain_step_at_the_end_of_the_body():
    (family, text), *_ = variants(PLAIN, 'walk')
    assert family == FAMILY
    assert 'put(i, i * 8 + 0x20);' in text
    assert 'off +=' not in text and 'for (i = 0; i < D_count; i++) {' in text


def test_flag_guard_set_to_the_entry_test():
    plain_guard = CHAIN.replace('guard_value = (D_limit > 0);\n', '').replace('if (guard_value)', 'if (D_limit > 0)')
    assert variants(plain_guard, 'menu')[0][1].count('for (var_s0 = 0;') == 1


def test_a_path_that_steps_twice_or_never_is_not_a_reduction():
    twice = CHAIN.replace('if (var_s0 != 2) {\n                        var_s1 += 0xA;', 'if (var_s0 != 2) {\n                        var_s1 += 0xA;\n                        var_s1 += 0xA;')
    assert not any(family == FAMILY and 'var_s0 * 10' in text for family, text in variants(twice, 'menu'))
    never = CHAIN.replace('if (var_s0 != 2) {\n                        var_s1 += 0xA;', 'if (var_s0 != 2) {\n                        var_s0 += 0;')
    assert not any('var_s0 * 10' in text for _, text in variants(never, 'menu'))


def test_left_alone():
    assert not variants(PLAIN.replace('i = 0;', 'i = 1;'), 'walk')
    assert not variants(PLAIN.replace('i += 1;\n', 'i += 1;\n            if (i > 9) break;\n'), 'walk')
    assert not variants(PLAIN.replace('        } while (i < D_count);\n    }\n', '        } while (i < D_count);\n    }\n    use(off);\n'), 'walk')
    assert not variants(PLAIN.replace('put(i, off);', 'off = 3;\n            put(i, off);'), 'walk')
    assert not variants('void f(void) { g(); }', 'f')


def test_read_after_the_step_is_left_alone():
    after = PLAIN.replace('off += 8;\n            i += 1;', 'off += 8;\n            put(0, off);\n            i += 1;')
    assert not variants(after, 'walk')


def test_chain_without_steps_is_a_switch_on_the_counter():
    source = CHAIN.replace('var_s1 += 0xA;\n', '').replace('draw(0xA0, var_s1);', 'draw(0xA0, 7);').replace(
        '    var_s1 = 0x50;\n', '')
    got = variants(source, 'menu')
    assert got and {family for family, _ in got} == {SWITCH_FAMILY}
    assert 'case 1: shown(0xA6); break;' in got[0][1]
