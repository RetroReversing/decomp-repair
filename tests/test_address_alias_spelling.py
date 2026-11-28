import re

from decomprepair.address_alias_spelling import FAMILY, REPAIR, SECOND, variants

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


BLOB = """extern u8 D_80054900[];
extern u8 D_800549D0[];
extern s32 D_80010000;

void task(Task *t, s32 other)
{
    t->boot = D_80054900;
    t->boot_size = D_800549D0 - D_80054900;
    if (other) {
        t->code = D_800549D0;
    }
}
"""
BLOB_ASM = ('lui $v1, %hi(D_800549D0)\n addiu $v1, $v1, %lo(D_800549D0)\n'
            ' lui $v0, %hi(D_800549D0)\n addiu $v0, $v0, %lo(D_800549D0)\n'
            ' lui $a0, %hi(D_80054900)\n addiu $a0, $a0, %lo(D_80054900)\n')


def _second(source=BLOB, asm=''):
    return [text for family, text in variants(source, 'task', '', asm) if family == SECOND]


def test_a_later_use_of_an_address_gets_a_second_automatic_name():
    found = _second(asm=BLOB_ASM)
    want = BLOB.replace('t->code = D_800549D0;', 't->code = data_800549D0;') \
               .replace('extern u8 D_800549D0[];\n', 'extern u8 data_800549D0[];\nextern u8 D_800549D0[];\n')
    assert want in found, found
    # the target builds D_80054900 only once, so it keeps its one name
    assert not any('data_80054900' in text for text in found)
    # never every use: that would be the same program under another name
    assert all('= D_800549D0 - ' in text or 't->code = D_800549D0;' in text for text in found)


def test_without_assembly_every_repeated_address_is_tried_and_an_existing_second_name_is_left_alone():
    assert any('data_80054900' in text for text in _second())
    assert _second(_second(asm=BLOB_ASM)[0], BLOB_ASM) == []


def test_elements_and_scalar_values_are_not_address_uses():
    elements = BLOB.replace('t->code = D_800549D0;', 't->code = D_800549D0[0];')
    assert _second(elements, BLOB_ASM) == []
    scalar = BLOB.replace('t->boot = D_80054900;', 't->boot = &D_80010000; t->size = D_80010000;')
    assert not any('data_80010000' in text for text in _second(scalar))
