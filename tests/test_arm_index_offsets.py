"""A switch's arms that read consecutive slots of two tables, written with the switch's index in the address."""
import re

from decomprepair.arm_index_offsets import FAMILY, variants

CODE = '''typedef int s32;
extern void use(void *, void *, s32);
void run(char *ent)
{
    s32 j;
    for (j = 0; j < 3; j++) {
        switch (j) {
        case 0:
            use(*(void **)((char *) ent + 0x418), (char *) ent + 0x438, 0xA60);
            break;
        case 1:
            use(*(void **)((char *) ent + 0x41C), (char *) ent + 0x448, 0x860);
            break;
        case 2:
            use(*(void **)((char *) ent + 0x420), (char *) ent + 0x458, 0xA60);
            break;
        }
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_arm_offsets_that_step_with_the_case_value_take_the_switch_variable():
    children = variants(CODE, 'run')
    assert [family for family, _ in children] == [FAMILY]
    text = squash(children[0][1])
    assert 'use(*(void **)((char *) ent + (0x418 + j * 4)), (char *) ent + (0x438 + j * 16), 0xA60);' in text
    assert 'case 1: use(*(void **)((char *) ent + (0x418 + j * 4)), (char *) ent + (0x438 + j * 16), 0x860);' in text
    assert '0x41C' not in text and '0x458' not in text
    assert 'case 2: use(*(void **)((char *) ent + (0x418 + j * 4)), (char *) ent + (0x438 + j * 16), 0xA60);' in text


def test_m2c_field_offsets_and_hex_case_values_are_read_too():
    code = CODE.replace('*(void **)((char *) ent + 0x418)', 'M2C_FIELD(ent, void **, 0x418)')
    code = code.replace('*(void **)((char *) ent + 0x41C)', 'M2C_FIELD(ent, void **, 0x41C)')
    code = code.replace('*(void **)((char *) ent + 0x420)', 'M2C_FIELD(ent, void **, 0x420)').replace('case 2:', 'case 0x2:')
    text = squash(variants(code, 'run')[0][1])
    assert 'M2C_FIELD(ent, void **, (0x418 + j * 4))' in text


def test_offsets_without_a_progression_two_arms_or_an_assigned_variable_are_left_alone():
    assert variants(CODE.replace('0x41C', '0x430'), 'run')[0][1].count('j * 4') == 0
    two = CODE.replace('        case 2:\n            use(*(void **)((char *) ent + 0x420), (char *) ent + 0x458, 0xA60);\n            break;\n', '')
    assert variants(two, 'run') == []
    assert variants(CODE.replace('0xA60);\n            break;\n        }', '0xA60);\n            j = 2;\n            break;\n        }'), 'run') == []
    assert variants(CODE, 'missing') == []
