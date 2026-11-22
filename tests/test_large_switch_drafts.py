"""m2c's large-switch drafts made compilable without changing what they do (large_switch_drafts.py)."""

import re

from decomprepair.large_switch_drafts import (
    cross_switch_cases,
    float_loads,
    float_pointer_arguments,
    placeholder_arguments,
    rewrite,
    unprototyped_externs,
)

NESTED = """void f(s32 a, s32 b) {
    switch (a) {                                    /* switch 1 */
    case 1:                                         /* switch 1 */
        if (b) {
            g(1);
        } else {
            switch (b) {                            /* switch 2 */
            case 3:                                 /* switch 2 */
            case 3:                                 /* switch 1 */
                g(3);
                break;
            default:                                /* switch 2 */
            default:                                /* switch 1 */
                g(0);
                break;
            }
        }
        break;
    }
}
"""


def test_a_case_of_the_outer_switch_inside_the_inner_one_becomes_a_label_and_a_jump():
    out = cross_switch_cases(NESTED)
    assert 'switch_1_3:' in out and 'case 3: goto switch_1_3;' in out
    assert 'switch_1_default:' in out and 'default: goto switch_1_default;' in out
    assert len(re.findall(r'\bcase 3:', out)) == 2 and len(re.findall(r'(?<!_)\bdefault:', out)) == 2  # one each
    outer = out.index('/* switch 1 */')
    assert out.index('case 3: goto switch_1_3;') < out.index('/* switch 2 */') and outer < out.index('goto')


def test_a_case_inside_a_nested_block_of_its_own_switch_is_left_alone():
    source = """void f(s32 a) {
    switch (a) {                                    /* switch 1 */
    case 1:                                         /* switch 1 */
        if (a) {
        case 2:                                     /* switch 1 */
            g();
        }
        break;
    }
}
"""
    assert cross_switch_cases(source) == source


def test_only_callees_with_disagreeing_calls_lose_their_parameter_list():
    source = """M2C_UNK sound(void *, u16, void *, f32);         /* extern */
s32 same(void *, s32);                              /* extern */

void f(void *a) {
    sound(a, 1U);
    sound(a, 2U, a, 1.0f);
    same(a, g(1, 2));
}
"""
    out = unprototyped_externs(source)
    assert 'M2C_UNK sound();' in out and 's32 same(void *, s32);' in out


def test_float_reads_and_argument_placeholders():
    assert float_loads('x = (f32) *((i * 0x18) + p);') == 'x = *(f32 *)((i * 0x18) + p);'
    assert placeholder_arguments('r = f(2U, nanf) + 1;') == 'r = f(2U) + 1;'
    assert float_pointer_arguments('f(a, M2C_BITWISE(void *, temp_a2), b);') == 'f(a, *(void **)&temp_a2, b);'


def test_a_draft_with_nothing_to_repair_is_declined():
    assert rewrite('void f(void) {\n    g();\n}\n') is None


def test_a_case_outside_every_switch_becomes_a_label_the_switch_jumps_to():
    source = """void f(s32 a, s32 b) {
    switch (a) {                                    /* switch 1 */
    case 1:                                         /* switch 1 */
        g(1);
        break;
    }
    if (b) {
        g(2);
    } else {
    case 2:                                         /* switch 1 */
        g(3);
    }
}
"""
    out = cross_switch_cases(source)
    assert 'switch_1_2:' in out and 'case 2: goto switch_1_2;' in out
    assert 'case 2:                                         /* switch 1 */' not in out
