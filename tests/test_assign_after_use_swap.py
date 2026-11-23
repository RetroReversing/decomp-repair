from decomprepair.assign_after_use_swap import FAMILY, variants

SOURCE = '''void f(u16 *rec, char *obj)
{
    u16 idx;
    void *p;

    idx = rec[20];
    (*(u16 *)((char *)(p) + 0x1BC)) += table[idx * 2];
    p = obj + (idx * 2);
    done();
}
'''


def made(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_assignment_goes_before_the_use_or_into_it():
    first, inside = made()
    assert first.index('p = obj + (idx * 2);') < first.index('+= table[idx * 2];')
    assert first.count('p = ') == 1
    assert '(p = obj + (idx * 2))' in inside and inside.count('p = ') == 1
    assert 'p = obj + (idx * 2);\n' not in inside


def test_a_local_mentioned_earlier_stays():
    other = SOURCE.replace('    idx = rec[20];\n', '    idx = rec[20];\n    p = obj;\n')
    assert not made(other)


def test_a_call_in_the_use_or_the_assignment_stays():
    assert not made(SOURCE.replace('table[idx * 2]', 'lookup(idx)'))
    assert not made(SOURCE.replace('obj + (idx * 2)', 'find(obj, idx)'))
