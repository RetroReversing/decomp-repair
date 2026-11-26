"""A record's first field narrowed to the target's load width, the padding widened to keep the size."""
from decomprepair import record_first_field_width as r

SOURCE = '''typedef struct { u16 f0; u8 pad[622]; } Slot;
extern Slot gSlots[];

s32 f(s32 i) {
    return gSlots[i].f0 == 0;
}
'''
ASM = '''lui        $at, %hi(gSlots)
addu       $at, $at, $v0
lbu        $v0, %lo(gSlots)($at)
'''


def test_the_field_takes_the_load_width_and_the_padding_the_rest():
    [(family, text)] = r.variants(SOURCE, 'f', ASM)
    assert family == 'record_first_field_width'
    assert 'typedef struct { u8 f0; u8 pad[623]; } Slot;' in text
    assert text.replace('u8 f0; u8 pad[623]', 'u16 f0; u8 pad[622]') == SOURCE  # nothing else changed


def test_nothing_when_the_widths_agree_or_differ_or_there_is_no_asm():
    assert r.variants(SOURCE, 'f', ASM.replace('lbu', 'lhu')) == []
    assert r.variants(SOURCE, 'f', ASM + ASM.replace('lbu', 'lhu')) == []
    assert r.variants(SOURCE, 'f', ASM.replace('lbu', 'lw')) == []
    assert r.variants(SOURCE, 'f', '') == []


def test_it_declares_itself():
    assert r.REPAIR['families'] == ('record_first_field_width',)
