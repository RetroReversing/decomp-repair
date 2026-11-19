"""An assignment written where its value is first used."""
from decomprepair import assignment_use_repairs as a

MOVED = '''void f(void *arg0) {
    s32 temp_a0;

    temp_a0 = *(s32 *)((char *)arg0 + 0);
    *(s8 *)((char *)arg0 + 0x18) = 0;
    *(s16 *)((char *)arg0 + 0x14) = 0;
    if (temp_a0) {
        g(temp_a0);
    }
}
'''
INLINE = '''s32 f(s32 arg1, s32 arg3, s32 arg4) {
    s32 temp_s0;
    s32 temp_s1;

    temp_s0 = arg4 * 0x1228;
    temp_s1 = arg1 + arg3;
    g(temp_s0 + D, temp_s1);
    h(temp_s1);
    return 0;
}
'''


def test_moved_to_its_use():
    # An N64 function at 98.8%: the load after the stores, exact.
    texts = [t for _, t in a.variants(MOVED, 'f')]
    assert any('= 0;\n    temp_a0 = *(s32 *)((char *)arg0 + 0);\n    if (temp_a0) {' in t for t in texts)
    assert any('    if ((temp_a0 = *(s32 *)((char *)arg0 + 0))) {' in t for t in texts)


def test_written_into_the_call():
    # An N64 function at 98.2%: exact with the sum assigned inside the call's arguments.
    texts = [t for _, t in a.variants(INLINE, 'f')]
    assert any('    g(temp_s0 + D, (temp_s1 = arg1 + arg3));\n    h(temp_s1);' in t for t in texts)


def test_left_alone_when_an_input_changes_first():
    changed = MOVED.replace('    *(s8 *)((char *)arg0 + 0x18) = 0;\n', '    arg0 = k();\n')
    assert a.variants(changed, 'f') == []
