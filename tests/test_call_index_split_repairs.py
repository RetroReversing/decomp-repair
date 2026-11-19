"""A table element's index kept before a call and the element read through the table after it."""
from decomprepair import call_index_split_repairs as c

SOURCE = '''s16 f(s32 arg0, u16 arg1) {
    u16 *temp_s0;
    u16 temp_s1;

    temp_s0 = ((arg0 & 0xF) * 2) + D_80112EBE;
    g();
    temp_s1 = *temp_s0;
    *temp_s0 = arg1;
    h();
    return (s16) temp_s1;
}
'''


def test_the_index_before_and_the_element_after():
    # An N64 function at 89%: exact this way.
    (family, out), = c.variants(SOURCE, 'f')
    assert family == 'pointer_index_after_call'
    assert '''    __repair_index = arg0 & 0xF;
    g();
    temp_s1 = ((u16 *) D_80112EBE)[__repair_index];
    ((u16 *) D_80112EBE)[__repair_index] = arg1;''' in out
    assert 'temp_s0' not in out


def test_left_alone_otherwise():
    assert c.variants(SOURCE.replace('* 2) +', '* 4) +'), 'f') == []  # not the element size
    assert c.variants(SOURCE.replace('    g();\n', ''), 'f') == []  # no call before the use
    assert c.variants(SOURCE.replace('    temp_s1 = *temp_s0;', '    temp_s1 = *(temp_s0 + 1);'), 'f') == []
    assert c.variants(SOURCE.replace('    g();\n', '    g();\n    arg0 = 1;\n'), 'f') == []  # index input changes
