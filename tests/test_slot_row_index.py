from decomprepair import registry
from decomprepair import slot_row_index as repair

SOURCE = '''extern Obj *gTable[];
extern Label *gRows[];

void f(s32 n)
{
    s32 slot;
    s32 off;
    Obj **ps;
    s32 k;
    Label *other;
    slot = n & 0xFFFF;
    off = slot * 4;
    ps = (Obj **)((char *)gTable + off);
    for (k = 0; k < n; k++)
    {
        other = *(Label **)((char *)gRows + k * 16 + off);
        g(other, *ps, slot);
        h((*ps)->x);
    }
}
'''


def texts(source=SOURCE):
    return [t for _, t in repair.variants(source, 'f')]


def test_the_slot_pointer_and_the_row_use_become_indexes_in_one_child():
    found = texts()
    assert len(found) == 1
    text = found[0]
    assert 'other = gRows[k][slot];' in text
    assert 'g(other, gTable[slot], slot);' in text and 'h((gTable[slot])->x);' in text
    assert 'extern Label *gRows[][4];' in text
    assert 'off = slot * 4;' not in text and 'ps = ' not in text


def test_the_pointer_alone_is_offered_when_no_row_table_is_read():
    source = SOURCE.replace('other = *(Label **)((char *)gRows + k * 16 + off);', 'other = 0;')
    found = texts(source)
    assert found and 'g(other, gTable[slot], slot);' in found[0] and 'gRows' not in found[0].split('void f')[1]


def test_a_use_that_is_not_covered_leaves_the_function_alone():
    other_use = SOURCE.replace('g(other, *ps, slot);', 'g(other, *ps, off);')
    assert not texts(other_use)
    pointer_used = SOURCE.replace('g(other, *ps, slot);', 'g(other, ps, slot);')
    assert not texts(pointer_used)
    rows_used_elsewhere = SOURCE.replace('h((*ps)->x);', 'h(gRows[1]);')
    assert not texts(rows_used_elsewhere)


def test_it_is_declared_for_every_lane():
    declared = registry.get('slot_row_index')
    assert declared is not None and registry.problems(declared) == []
    assert registry.run('slot_row_index', source=SOURCE, name='f')
