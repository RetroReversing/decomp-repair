"""m2c's goto list walk written as a `while` with a `break` (a 2,503-instruction update, 11416 -> 10131)."""
from decomprepair.list_search_while import FAMILY, variants

SOURCE = """void unlink(void)
{
    void *p;
    void *next;

    if (gTarget != NULL) {
        p = (*(void **)((char *)(gTarget) + 0x18));
        if (p != NULL) {
loop_95:
            next = (*(void **)((char *)(p) + 0x14));
            if (next != gTarget) {
                p = next;
                if (p != NULL) {
                    goto loop_95;
                }
            } else {
                (*(void **)((char *)(p) + 0x14)) = (*(void **)((char *)(next) + 0x14));
            }
        }
        query(gTarget);
    }
}
"""

WHILE = """        while (p != NULL) {
            next = (*(void **)((char *)(p) + 0x14));
            if (next == gTarget) {
                (*(void **)((char *)(p) + 0x14)) = (*(void **)((char *)(next) + 0x14));
                break;
            }
            p = next;
        }
        query(gTarget);
"""


def test_the_walk_becomes_a_while_with_a_break():
    found = variants(SOURCE, 'unlink')
    assert [family for family, _ in found] == [FAMILY]
    text = found[0][1]
    assert WHILE in text
    assert 'loop_95' not in text and 'goto' not in text


def test_two_walks_get_a_child_each_and_one_together():
    second = SOURCE.replace('gTarget', 'gOther').replace('loop_95', 'loop_99').replace('void unlink', 'void unlink2')
    source = SOURCE + second
    found = [text for _, text in variants(source, 'unlink')]
    assert len(found) == 3
    assert 'goto' not in found[-1] and found[-1].count('while (p != NULL)') == 2


def test_a_label_used_elsewhere_is_left_alone():
    source = SOURCE.replace('        query(gTarget);', '        query(gTarget);\n        goto loop_95;')
    assert variants(source, 'unlink') == []
