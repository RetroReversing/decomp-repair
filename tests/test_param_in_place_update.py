"""A parameter masked into a temporary, written back into the parameter."""
import re

from decomprepair.param_in_place_update import FAMILY, variants

CODE = '''typedef int s32;
extern s32 gOff;
extern void use(s32);
s32 run(s32 arg0, s32 arg1, s32 arg3)
{
    s32 temp;
    s32 other;
    other = arg0 + arg1;
    temp = arg3 & (-(gOff == 0));
    if (temp != 0) {
        use(temp + other);
    }
    return other;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_temporary_is_written_back_into_the_parameter():
    children = variants(CODE, 'run')
    assert [family for family, _ in children] == [FAMILY]
    text = squash(children[0][1])
    assert 'arg3 &= (-(gOff == 0));' in text and 'if (arg3 != 0) { use(arg3 + other);' in text
    assert 's32 temp;' not in text and 's32 other;' in text


def test_a_parameter_read_afterwards_or_in_a_loop_or_a_wider_temporary_is_left_alone():
    assert variants(CODE.replace('return other;', 'return other + arg3;'), 'run') == []
    assert variants(CODE.replace('    temp = arg3', '    while (other--) temp = arg3'), 'run') == []
    assert variants(CODE.replace('s32 temp;', 'short temp;'), 'run') == []
