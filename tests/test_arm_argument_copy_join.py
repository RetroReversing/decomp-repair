"""arm_argument_copy_join: a call's first argument copied on two paths of the switch before it, with the masked value local.

Shape of a 150-instruction KMC effect spawner (saved best 60: the tail after the switch had `move $a3` before the
`andi`; each half alone scored 520 and 115, the combination with two sets of the copy 0)."""
from decomprepair import arm_argument_copy_join as w

SOURCE = """void *start(u16 kind, s32 tag, s32 extra, u16 tail);
void apply(void *obj, s32 word, u16 half, s32 tag);

void *make(u16 kind, s32 tag, s32 word, u16 half)
{
    s32 sel;
    void *rec;
    u16 flags;

    flags = kind;
    rec = start(1, 0, 0, 0);
    sel = flags & 0xF000;
    switch (sel) {
    case 0x1000:
        (*(s16 *)((char *)rec + 0x3C)) = 0;
        break;
    case 0x3000:
        (*(s16 *)((char *)rec + 0x3C)) = 1;
        break;
    case 0x2000:
        (*(s16 *)((char *)rec + 0x3C)) = 2;
        break;
    }
    (*(s16 *)((char *)(rec) + 0x3E)) = (s16) (flags & 0xFFF);
    apply(rec, word, half, tag);
    return rec;
}
"""


def test_the_copy_is_set_in_one_arm_and_at_the_label_the_others_reach():
    found = w.variants(SOURCE, 'make')
    assert [family for family, _ in found] == [w.FAMILY] * 3
    revised = found[0][1]
    assert revised.index('void *arg_copy;') < revised.index('flags = kind;') and 'u16 mask_value;' in revised
    assert revised.count('arg_copy = rec;') == 2 and revised.count('goto arg_join;') == 1
    assert revised.index('arg_copy = rec;') < revised.index('case 0x3000:')
    assert revised.index('goto arg_join;') < revised.index('case 0x2000:') < revised.index('default:')
    assert 'default:\n    arg_join: arg_copy = rec;' in revised
    assert revised.count('break;') == 1
    assert 'mask_value = flags & 0xFFF;' in revised
    assert '(*(s16 *)((char *)(rec) + 0x3E)) = mask_value;' in revised
    assert 'apply(arg_copy, word, half, tag);' in revised


def test_each_arm_takes_its_turn_setting_the_copy_itself():
    found = [text for _, text in w.variants(SOURCE, 'make')]
    where = [text.index('arg_copy = rec;\n        break;') for text in found]
    labels = [[text.index(f'case {value}:') for value in ('0x1000', '0x3000', '0x2000')] for text in found]
    assert where[0] < labels[0][1] and labels[1][1] < where[1] < labels[1][2] and labels[2][2] < where[2]
    assert [text.count('goto arg_join;') for text in found] == [1, 1, 2]
    assert all(text.index('default:') > where[i] for i, text in enumerate(found))


def test_applied_once_and_declined_when_the_shape_is_not_there():
    revised = w.variants(SOURCE, 'make')[0][1]
    assert w.variants(revised, 'make') == []
    assert w.variants(SOURCE.replace('    (*(s16 *)((char *)(rec) + 0x3E)) = (s16) (flags & 0xFFF);\n', ''), 'make') == []
    assert w.variants(SOURCE.replace('    case 0x2000:', '    default:\n        flags = 0;\n        break;\n    case 0x2000:'), 'make') == []
    assert w.variants(SOURCE.replace('        (*(s16 *)((char *)rec + 0x3C)) = 2;\n        break;', '        (*(s16 *)((char *)rec + 0x3C)) = 2;'),
                      'make') == []
    assert w.variants(SOURCE.replace('apply(rec, word', 'apply(flags, word'), 'make') == []
    assert w.variants(SOURCE.replace('    apply(rec', '    start(1, 0, 0, 0);\n    apply(rec'), 'make') == []
