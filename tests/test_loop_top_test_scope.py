"""A loop whose first statement is its exit test, with a local of its own declared in its body."""
import re

from decomprepair.loop_top_test_scope import FAMILY, variants

CODE = '''typedef short s16;
extern s16 *gTable[];
int search(int want)
{
    s16 *entry;
    s16 **cursor;
    int found;
    cursor = gTable;
    found = 0;
    for (;;)
    {
        if (found)
            break;
        entry = *cursor;
        if (entry == 0)
            break;
        cursor += 1;
        if (*entry == want)
            found = 1;
    }
    return found;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_local_used_only_in_the_loop_is_declared_at_the_top_of_its_body():
    children = variants(CODE, 'search')
    assert [family for family, _ in children] == [FAMILY]
    text = squash(children[0][1])
    assert 'for (;;) { s16 *entry; if (found) break;' in text
    assert text.count('s16 *entry;') == 1 and 's16 **cursor;' in text


def test_a_local_used_outside_or_a_loop_without_a_top_exit_is_left_alone():
    assert variants(CODE.replace('return found;', 'return entry != 0;'), 'search') == []
    assert variants(CODE.replace('if (found)\n            break;\n', ''), 'search') == []
    assert variants(CODE.replace('s16 *entry;', 'volatile s16 *entry;'), 'search') == []
