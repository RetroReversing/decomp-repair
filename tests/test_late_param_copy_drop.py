from decomprepair import late_param_copy_drop

SOURCE = '''void func(void *obj_in) {
    void *obj;
    s32 next;
    *(s32 *)((char *)(obj) + 0x34) += 1;
    obj = obj_in;
    next = *(s32 *)((char *)(obj) + 0x3C);
    *(s32 *)((char *)(obj) + 0x40) = next;
}
'''


def test_reads_use_the_parameter():
    family, child = late_param_copy_drop.variants(SOURCE, 'func')[0]
    assert family == 'late_param_copy_drop'
    assert 'obj = obj_in' not in child and 'void *obj;' not in child
    assert '*(s32 *)((char *)(obj_in) + 0x34) += 1;' in child
    assert 'next = *(s32 *)((char *)(obj_in) + 0x3C);' in child


def test_a_copy_made_before_every_read_is_left_alone():
    early = SOURCE.replace('    *(s32 *)((char *)(obj) + 0x34) += 1;\n    obj = obj_in;\n',
                           '    obj = obj_in;\n    *(s32 *)((char *)(obj) + 0x34) += 1;\n')
    assert late_param_copy_drop.variants(early, 'func') == []


def test_a_local_written_elsewhere_or_a_used_parameter_declines():
    written = SOURCE.replace('+ 0x40) = next;', '+ 0x40) = next;\n    obj = 0;')
    assert late_param_copy_drop.variants(written, 'func') == []
    used = SOURCE.replace('+ 0x40) = next;', '+ 0x40) = obj_in;')
    assert late_param_copy_drop.variants(used, 'func') == []
