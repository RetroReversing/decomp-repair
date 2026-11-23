"""A pointer a call returned, tested and used throughout the arm, copied into a local of its own."""
from decomprepair import call_result_arm_local as t

SOURCE = '''void f(void *rec)
{
    void *temp_v0;

    temp_v0 = make(0);
    *((void **) (((char *) rec) + 0x514)) = temp_v0;
    if (temp_v0 != NULL)
    {
        link(temp_v0);
        *((s32 *) (((char *) temp_v0) + 0xC)) = 0;
        *((s16 *) (((char *) temp_v0) + 0x24)) = 0x40;
    }
    after(temp_v0);
}
'''


def test_the_arm_reads_a_copy_taken_at_its_head():
    # A 1133-instruction effect spawner: a constructor call's result was the base of twenty stores in the arm; the target
    # copies it to its saved register only on the path that takes the arm (5630 -> 5560).
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert len(out) == 1
    child = out[0]
    assert '    void *temp_v0_arm;\n' in child
    assert 'if (temp_v0 != NULL)\n    {\n        temp_v0_arm = temp_v0;\n        link(temp_v0_arm);' in child
    assert '(char *) temp_v0_arm) + 0x24)) = 0x40;' in child
    assert '*((void **) (((char *) rec) + 0x514)) = temp_v0;' in child and 'after(temp_v0);' in child


def test_left_alone_otherwise():
    assert t.variants(SOURCE.replace('temp_v0 = make(0);', 'temp_v0 = global;'), 'f') == []  # not a call result
    assert t.variants(SOURCE.replace('        link(temp_v0);\n', '        temp_v0 = other;\n'), 'f') == []  # assigned in the arm
    assert t.variants(SOURCE.replace('        link(temp_v0);\n        *((s32 *) (((char *) temp_v0) + 0xC)) = 0;\n', ''),
                      'f') == []  # one use only


def test_it_declares_itself():
    from decomprepair import registry
    assert any(r.module == 'call_result_arm_local' for r in registry.declared())
