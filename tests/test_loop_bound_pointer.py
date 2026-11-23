"""A loop bounded by a global that its body also reads, through a volatile pointer set in the loop's test."""
import re

from decomprepair.loop_bound_pointer import FAMILY, variants

CODE = '''typedef int s32;
typedef unsigned short u16;
extern s32 gCount;
extern s32 gOther;
extern void work(s32);
void run(void)
{
    u16 i;
    for (i = 0; i < gCount; i++) {
        switch (gCount) {
        case 2:
            work(1);
            break;
        }
        work(i);
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_bound_and_the_bodys_reads_go_through_a_volatile_pointer():
    children = variants(CODE, 'run')
    assert [family for family, _ in children] == [FAMILY, FAMILY]
    first, second = (squash(text) for _, text in children)
    assert 'void run(void) { volatile s32 *loop_bound_ptr; u16 i;' in first
    assert 'for (i = 0; i < *(loop_bound_ptr = &gCount); i++) { switch (*loop_bound_ptr) {' in first
    assert 'for (i = 0; i < *(loop_bound_ptr = &gCount); i++) { switch (gCount) {' in second


def test_other_loops_are_left_alone():
    assert variants(CODE.replace('i < gCount', 'i < 4'), 'run') == []
    assert variants(CODE.replace('extern s32 gCount;', 'extern volatile s32 gCount;'), 'run') == []
    assert variants(CODE.replace('work(i);', 'gCount = 3;'), 'run') == []
    assert variants(CODE.replace('work(1);', 'work(*(&gCount));'), 'run') == []
    assert variants(CODE, 'missing') == []


def test_a_read_before_the_loop_stays_a_plain_read():
    code = CODE.replace('    u16 i;', '    u16 i;\n    work(gCount);')
    text = squash(variants(code, 'run')[0][1])
    assert 'work(gCount); for (i = 0; i < *(loop_bound_ptr = &gCount);' in text
