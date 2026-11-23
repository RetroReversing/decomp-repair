import re

from decomprepair.address_alias_spelling import FAMILY, REPAIR, variants

HEADER = """extern s32 D_800D2858;
extern s32 D_800D2864;
extern s32 D_80100000;
"""

SOURCE = """void menu(void *a, void *b, void *c)
{
    s32 *p;
    p = &D_800D2858;
    fmt(a, &D_800D2864, look(1));
    fmt(b, &D_800D2864, look(2));
    fmt(c, &D_800D2864, look(3));
    fmt(a, &D_800D2864, look(4));
    sink(p);
}
"""

RENAMED = SOURCE.replace('D_800D2864', 'sFmtName').replace('extern s32 D_800D2864;', '')
ASM = 'glabel menu\n lui $a1, %hi(D_800D2864)\n addiu $a1, $a1, %lo(D_800D2864)\n lui $a2, %hi(D_800D2858)\n lui $a3, %hi(D_80100000)\n'
RENAMED_HEADER = 'extern s32 D_800D2858;\nextern s32 sFmtName;\n'


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _found(source=SOURCE, header=HEADER, asm='', name='menu'):
    return [_flat(text) for family, text in variants(source, name, header, asm) if family == FAMILY]


ALIAS = '((s32 *) ((u8 *) &D_800D2858 + 0xC))'


def test_a_run_of_the_uses_is_spelled_as_the_other_symbols_address_plus_an_offset():
    found = _found()
    assert found
    middle = [t for t in found if f'fmt(b, {ALIAS}, look(2)); fmt(c, {ALIAS}, look(3));' in t
              and 'fmt(a, &D_800D2864, look(1))' in t and 'fmt(a, &D_800D2864, look(4))' in t]
    assert middle, found


def test_the_whole_set_is_never_one_child_and_longer_runs_come_first():
    found = _found()
    assert all(t.count(ALIAS) < 4 for t in found)
    assert found[0].count(ALIAS) == 3


def test_a_renamed_symbol_takes_its_address_from_the_assembly_names():
    assert _found(RENAMED, RENAMED_HEADER) == []
    found = _found(RENAMED, RENAMED_HEADER, ASM)
    assert any('fmt(b, ((s32 *) ((u8 *) &D_800D2858 + 0xC)), look(2))' in t for t in found), found


def test_nothing_without_a_second_symbol_in_reach_or_for_a_single_use():
    far = SOURCE.replace('D_800D2858', 'D_80100000')
    assert _found(far, HEADER) == []
    one = SOURCE.replace('    fmt(b, &D_800D2864, look(2));\n', '').replace('    fmt(c, &D_800D2864, look(3));\n', '') \
                .replace('    fmt(a, &D_800D2864, look(4));\n', '')
    assert _found(one) == []


def test_only_whole_call_arguments_are_rewritten():
    sums = SOURCE.replace('fmt(b, &D_800D2864, look(2))', 'fmt(b, (s32 *) ((u8 *) &D_800D2864 + 4), look(2))')
    for text in _found(sums):
        assert '((u8 *) ((s32 *) ((u8 *) &D_800D2858' not in text


def test_it_declares_itself_with_the_assembly_and_header():
    assert REPAIR['variants'] is variants and REPAIR['needs'] == ('source', 'name', 'header', 'asm')
