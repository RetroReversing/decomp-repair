"""A masked byte kept in a halfword local, retyped narrow with its mask dropped (and the reverse)."""
from decomprepair import mask_local_retype as r

SOURCE = '''extern s32 gA;
extern s32 gB;
extern u16 gOut[];

void f(void) {
    s16 flag;
    s32 slot;

    flag = ((u32) ~(gA - gB) >> 0x1F) & 0xFF;
    slot = gA & 6;
    gOut[slot] = flag;
    gOut[slot + 1] = flag;
}
'''
ASM = 'andi       $a0, $a0, 0xFF\nsh         $a0, 0x0($at)\n'


def children(source=SOURCE, asm=ASM, family='mask_local_retype'):
    return [t for fam, t in r.variants(source, 'f', asm) if fam == family]


def test_retype_with_the_mask_dropped_comes_first_then_the_mask_kept():
    first, second = children()
    assert 'u8 flag;' in first and '& 0xFF;' not in first
    assert 'flag = ((u32) ~(gA - gB) >> 0x1F);' in first
    assert 'u8 flag;' in second and 'flag = ((u32) ~(gA - gB) >> 0x1F) & 0xFF;' in second
    assert 's32 slot;' in first and 'slot = gA & 6;' in first  # (a mask that is no byte mask is left alone)


def test_a_halfword_mask_gives_u16_and_a_word_local_keeps_one_child():
    out = children(SOURCE.replace('s16 flag;', 's32 flag;').replace('& 0xFF;', '& 0xFFFF;'), 'andi $a0, $a0, 0xFFFF\n')
    assert any('u16 flag;' in t and '& 0xFFFF' not in t for t in out)


def test_nothing_without_the_target_having_that_andi():
    assert r.variants(SOURCE, 'f', 'addu $a0, $a0, $a1\n') == []


def test_a_local_with_other_assignments_or_its_address_taken_is_left_alone():
    assert children(SOURCE.replace('gOut[slot + 1] = flag;', 'flag += 1;')) == []
    assert children(SOURCE.replace('gOut[slot + 1] = flag;', 'g(&flag);')) == []
    assert children(SOURCE.replace('    gOut[slot] = flag;', '    flag = gA;\n    gOut[slot] = flag;')) == []


def test_the_reverse_widens_an_unmasked_byte_local_the_target_masks():
    source = SOURCE.replace('s16 flag;', 'u8 flag;').replace(' & 0xFF;', ';')
    (out,) = children(source, family='narrow_unmask')
    assert 's32 flag;' in out and 'flag = (((u32) ~(gA - gB) >> 0x1F)) & 0xFF;' in out
    assert children(source, asm='addu $a0, $a0, $a1\n', family='narrow_unmask') == []


def test_it_declares_itself():
    assert r.REPAIR['variants'] is r.variants and set(r.REPAIR['families']) == {'mask_local_retype', 'narrow_unmask'}
