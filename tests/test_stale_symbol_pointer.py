from decomprepair import stale_symbol_pointer as S

SOURCE = '''extern char sCounts[];
void f(s32 a, s32 b) {
    s32 *ptr;
    if (a) {
        ptr = sCounts;
        *((u8 *) (((char *) ptr) + 0)) -= 1;
        g(a);
    }
    if (b) {
        *((u8 *) (((char *) ptr) + 1)) -= 1;
        g(b);
    }
}
'''


def children(source):
    return dict(S.variants(source, 'f'))


def test_every_read_of_the_web_becomes_the_array_and_the_assignment_goes():
    child = children(SOURCE)[S.FAMILY]
    assert 'ptr = sCounts' not in child
    assert 'sCounts[0] -= 1;' in child
    assert 'sCounts[1] -= 1;' in child


def test_only_the_reads_outside_the_block():
    child = children(SOURCE)[S.FAMILY_READ]
    assert 'ptr = sCounts;' in child
    assert '*((u8 *) (((char *) ptr) + 0)) -= 1;' in child
    assert 'sCounts[1] -= 1;' in child


def test_assignment_stays_when_the_pointer_has_another_use():
    child = children(SOURCE.replace('g(a);', 'g(ptr);'))[S.FAMILY]
    assert 'ptr = sCounts;' in child and 'sCounts[1] -= 1;' in child


def test_wider_elements_are_cast():
    source = SOURCE.replace('(u8 *) (((char *) ptr) + 1)', '(s16 *) (((char *) ptr) + 6)')
    assert '((s16 *) sCounts)[3] -= 1;' in children(source)[S.FAMILY]


def test_nothing_when_every_read_follows_in_the_block():
    source = SOURCE.replace('*((u8 *) (((char *) ptr) + 1)) -= 1;', '')
    assert S.variants(source, 'f') == []


def test_nothing_past_another_assignment():
    source = SOURCE.replace('if (b) {', 'if (b) {\n        ptr = other;')
    assert S.variants(source, 'f') == []
