"""named_symbol_block_copy and branch_join_address_local on a made-up warning banner in m2c's shape (no game's code)."""
from decomprepair.branch_join_address_local import FAMILY as HELD
from decomprepair.branch_join_address_local import variants as held
from decomprepair.call_load_temps_inline import variants as call_load_temps_inline
from decomprepair.named_symbol_block_copy import FAMILY, variants
from decomprepair.registry import declared

DRAFT = '''extern signed char D_80001000;
extern signed char D_80001001;
extern signed char D_80001002;
extern int D_80001004;
extern int D_80001008;
extern short D_8000100C;
extern unsigned short D_80002000;

void banner(void) {
    signed char *__base_D_80001000;
    char sp20[0x40];
    s32 sp60;
    s8 sp61;
    s8 sp62;
    s32 sp68;
    s32 sp6C;
    s16 sp70;

    __base_D_80001000 = &D_80001000;
    sp60 = (*__base_D_80001000);
    sp61 = D_80001001;
    sp62 = D_80001002;
    sp68 = D_80001004;
    sp6C = D_80001008;
    sp70 = D_8000100C;
    draw(&sp68, &sp60);
    if (D_80002000 != 0) {
        sp60 = (*__base_D_80001000);
        sp61 = D_80001001;
        sp62 = D_80001002;
        if (D_80002000 < 20) {
            print(sp20, "%d left", 20 - D_80002000);
        } else {
            print(sp20, "none left");
        }
        draw(sp20, &sp60);
    }
}
'''
ASM = '''addiu      $sp, $sp, -0xB0
sw         $ra, 0xAC($sp)
sw         $s0, 0xA8($sp)
addiu      $s0, $sp, 0x60
'''


def test_the_labelled_copies_become_block_copies_into_sized_buffers():
    (family, text), = variants(DRAFT, 'banner', ASM)
    assert family == FAMILY
    assert '__builtin_memcpy(&sp60, &D_80001000, 3);' in text
    assert '__builtin_memcpy(&sp68, &D_80001004, 10);' in text
    assert text.count('__builtin_memcpy(&sp60, &D_80001000, 3);') == 2
    assert 's32 sp60[2];' in text
    assert 's32 sp68[16];' in text  # up to the first register the frame saves
    assert 'sp61' not in text and 'sp70' not in text and '__base_D_80001000' not in text


def test_a_local_read_elsewhere_stays():
    assert variants(DRAFT.replace('draw(sp20, &sp60);', 'draw(sp20, &sp60, sp61);'), 'banner', ASM) == []


def test_the_held_address_is_set_before_the_branch():
    (_, copied), = variants(DRAFT, 'banner', ASM)
    (family, text), = held(copied, 'banner', ASM)
    assert family == HELD
    assert '__repair_held_address = &sp60;\n        if (D_80002000 < 20) {' in text
    assert 'draw(sp20, __repair_held_address);' in text
    assert 'draw(&sp68, &sp60);' in text
    assert held(copied, 'banner', '') == []


def test_both_are_declared():
    found = {repair.module for repair in declared()}
    assert {'named_symbol_block_copy', 'branch_join_address_local'} <= found


def test_a_char_read_does_not_stop_call_load_temps_inline():
    source = '''void f(char *p) {
    s32 t;

    t = *p;
    g(t);
}
'''
    assert call_load_temps_inline(source, 'f') == []
