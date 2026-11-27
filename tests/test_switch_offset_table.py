"""A sparse switch is renumbered from zero, its gaps written as empty arms, so the cases are dense."""
import re

from decomprepair import registry
from decomprepair.switch_offset_table import FAMILIES, FAMILY, variants

CODE = '''typedef unsigned char u8;
extern u8 *state;
extern void a(void);
extern void b(void);
extern void c(void);

void run(void)
{
    u8 temp_v0;

    temp_v0 = state[0x70];
    switch (temp_v0) {
    case 1:
        a();
        break;
    case 2:
    case 3:
    case 4:
    case 11:
        if (state[0x71] == 0) {
            b();
        } else {
        case 0:
        default:
            c();
        }
        break;
    }
    a();
}
'''

ASM = '''    addiu      $v1, $v0, -0x1
    sltiu      $v0, $v1, 0xb
    beqz       $v0, .L1
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def kids(source=CODE, asm=ASM):
    return [text for family, text in variants(source, 'run', asm) if family == FAMILY]


def test_labels_are_lowered_by_the_bias_and_the_gaps_break_at_the_end():
    first = squash(kids()[0])
    assert 'switch (temp_v0 - 1) {' in first
    assert 'case 0: a();' in first
    assert 'case 1: case 2: case 3: case 10:' in first
    assert 'case 4: case 5: case 6: case 7: case 8: case 9: break; }' in first
    assert 'case 11' not in first and 'default: c();' in first
    assert not re.search(r'case 0:\s*default', first), 'the alias of the default is removed'


def test_the_gap_labels_can_join_the_default_arm_instead():
    second = squash(kids()[1])
    assert 'case 4: case 5: case 6: case 7: case 8: case 9: default: c();' in second


def test_needs_the_targets_biased_range_check():
    assert not kids(asm='')
    assert not kids(asm='    sltiu      $v0, $v1, 0xb\n')
    assert not kids(asm='    addiu      $v1, $v0, -0x1\n    sltiu      $v0, $v1, 0x4\n')


def test_a_switch_that_already_subtracts_or_nests_is_left_alone():
    assert not kids(CODE.replace('switch (temp_v0)', 'switch (temp_v0 - 1)'))
    assert not kids(CODE.replace('a();\n        break;\n    case 2:', 'switch (b) { case 1: break; }\n        break;\n    case 2:'))


def test_the_module_declares_itself():
    assert FAMILIES == (FAMILY,)
    assert registry.problems(registry.get('switch_offset_table')) == []
