"""A call's narrowing conversions evaluated before the statement that sets the call's pointer argument."""
import re

from decomprepair.call_conversion_stage import FAMILY, variants

CODE = '''typedef float f32;
typedef int s32;
typedef unsigned short u16;
typedef unsigned int u32;
extern char gRows[][12];
extern void *make(s32, s32, void *, s32);
void run(f32 cx, f32 cy, u16 i)
{
    void *s;
    void *q;
    s = gRows[i];
    q = make((u16) (u32) cx, (u16) (u32) cy, s, i);
    use(q);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_conversions_are_set_before_the_pointer_statement():
    children = variants(CODE, 'run')
    assert [family for family, _ in children] == [FAMILY, FAMILY]
    wide, narrow = (squash(text) for _, text in children)
    assert 'void run(f32 cx, f32 cy, u16 i) { s32 staged_arg0; s32 staged_arg1; void *s;' in wide
    assert 'staged_arg0 = (u16) (u32) cx; staged_arg1 = (u16) (u32) cy; s = gRows[i]; q = make(staged_arg0, staged_arg1, s, i);' in wide
    assert 'u16 staged_arg0; u16 staged_arg1;' in narrow


def test_other_calls_are_left_alone():
    assert variants(CODE.replace('(u16) (u32) cx, (u16) (u32) cy', 'cx, cy'), 'run') == []
    assert variants(CODE.replace('    s = gRows[i];\n', '    s = pick(i);\n'), 'run') == []
    one = squash(variants(CODE.replace('(u16) (u32) cx', 'cx'), 'run')[0][1])
    assert 'staged_arg0 = (u16) (u32) cy;' in one and 'staged_arg1' not in one and 'make(cx, staged_arg0, s, i)' in one
    assert variants(CODE.replace('s, i);', 'gRows, i);'), 'run') == []
    assert variants(CODE, 'missing') == []
