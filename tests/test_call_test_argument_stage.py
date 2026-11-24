"""A call's zero-test argument staged in a local before the statement (a 2,503-instruction update, 20273 -> 19353)."""
from decomprepair.call_test_argument_stage import FAMILY, variants

SOURCE = """void update(void *arg0)
{
    void *r;
    s32 hit;

    if ((cast(&table, arg0 + 0x24, (*(void **)((char *)(r) + 0xD4)) != NULL, 0) << 0x18) != 0) {
        use(1);
    }
    hit = find(arg0, 1, ((*(s32 *)((char *)(r) + 0x60)) & 0x2000) != 0, 0);
    other(arg0 != 0, count(r) != 0);
}
"""


def children(source=SOURCE):
    found = variants(source, 'update')
    assert all(family == FAMILY for family, _ in found)
    return [text for _, text in found]


def test_each_test_is_staged_alone_and_both_together():
    found = children()
    assert len(found) == 3
    both = found[-1]
    assert '    void *stagedTest0;\n    s32 stagedTest1;\n    void *r;' in both
    assert ('    stagedTest0 = *(void **)((char *)(r) + 0xD4);\n'
            '    if ((cast(&table, arg0 + 0x24, stagedTest0 != NULL, 0) << 0x18) != 0) {') in both
    assert ('    stagedTest1 = (*(s32 *)((char *)(r) + 0x60)) & 0x2000;\n'
            '    hit = find(arg0, 1, stagedTest1 != 0, 0);') in both


def test_tests_without_a_load_or_with_a_call_are_left_alone():
    assert all('other(arg0 != 0, count(r) != 0);' in text for text in children())


def test_two_tests_on_one_line_are_both_staged_before_it():
    source = SOURCE.replace('other(arg0 != 0, count(r) != 0);', 'pair(*(s32 *)r != 0, ((s32 *)r)[1] != 0);')
    together = children(source)[-1]
    assert 'pair( stagedTest2 != 0, stagedTest3 != 0);' in together
    assert together.index('stagedTest2 = *(s32 *)r;') < together.index('stagedTest3 = ((s32 *)r)[1];') < together.index('pair(')


def test_an_else_if_header_is_not_staged():
    source = SOURCE.replace('    hit = find(', '    if (hit) {\n    } else if (find(').replace('0x2000) != 0, 0);', '0x2000) != 0, 0)) {\n    }')
    assert not any('0x2000;\n' in text for text in children(source))
