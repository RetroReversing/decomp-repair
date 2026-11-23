"""narrow_store_width: a word store of a value m2c narrowed, written as the narrow store the target has."""
from decomprepair import narrow_store_width as nsw
from decomprepair import registry

SOURCE = '''void f(void *rec, s32 *src) {
    *((s32 *) (((char *) rec) + 0x40)) = (s16) src[4];
    *((s32 *) (((char *) rec) + 0x44)) = (s16) src[5];
    *((s32 *) (((char *) rec) + 0x48)) = src[6];
}
'''
ASM = '''glabel f
/* 0 */  lw         $v0, 0x10($a1)
/* 4 */  sh         $v0, 0x40($a0)
/* 8 */  lw         $v0, 0x14($a1)
/* C */  sw         $v0, 0x44($a0)
'''


def test_a_site_the_target_stores_narrow_becomes_a_narrow_store():
    out = [text for _family, text in nsw.variants(SOURCE, 'f', asm=ASM)]
    assert len(out) == 1  # one site: 0x44 is a word store in the target
    assert '*((s16 *) (((char *) rec) + 0x40)) = src[4];' in out[0]
    assert '*((s32 *) (((char *) rec) + 0x44)) = (s16) src[5];' in out[0]


def test_every_site_with_the_narrow_store_is_one_more_child():
    asm = ASM.replace('sw         $v0, 0x44', 'sh         $v0, 0x44')
    out = [text for _family, text in nsw.variants(SOURCE, 'f', asm=asm)]
    assert len(out) == 3
    assert out[-1].count('*((s16 *)') == 2


def test_no_assembly_no_child():
    assert nsw.variants(SOURCE, 'f') == []
    assert nsw.variants(SOURCE, 'f', asm='glabel f\n  sw $v0, 0x40($a0)\n') == []


def test_a_byte_store_is_the_other_width():
    source = 'void f(void *rec, s32 v) {\n    *((u32 *) (((char *) rec) + 3)) = (u8) v;\n}\n'
    out = [text for _family, text in nsw.variants(source, 'f', asm='  sb $v0, 3($a0)\n')]
    assert out and '*((u8 *) (((char *) rec) + 3)) = v;' in out[0]


def test_it_declares_itself_to_the_registry():
    repair = registry.get('narrow_store_width')
    assert repair is not None and registry.problems(repair) == []


HOLD = '''void f(void *rec, f64 x) {
    s32 v;

    v = (s16) ((s32) x);
    *((s16 *) (((char *) rec) + 0x20)) = (s16) ((s32) x);
    g(v);
}
'''


def test_a_value_narrowed_twice_is_held_and_stored():
    out = [text for family, text in nsw.variants(HOLD, 'f', asm='  sh $a0, 0x20($s1)\n') if family == nsw.FAMILY_HOLD]
    assert out
    assert 'v = (s32) x;' in out[0] and '*((s16 *) (((char *) rec) + 0x20)) = v;' in out[0]


def test_a_sign_extension_in_the_target_blocks_the_hold():
    asm = '  sh $a0, 0x20($s1)\n  sll $v0, $a0, 16\n  sra $a0, $v0, 16\n'
    assert not [t for family, t in nsw.variants(HOLD, 'f', asm=asm) if family == nsw.FAMILY_HOLD]


def test_a_constant_word_store_the_target_stores_as_a_byte():
    # A 1133-instruction effect spawner: `*((s32 *) (rec + 0x28)) = 0x80;` where the target has `sb` (6305 -> 6105); the
    # same offset is a word in the flag update beside it, which stays.
    source = ('void f(void *rec) {\n    *((s32 *) (((char *) rec) + 0x28)) = (s32) ((*((s32 *) (((char *) rec) + 0x28))) | 4);\n'
              '    *((s32 *) (((char *) rec) + 0x28)) = 0x80;\n    *((s32 *) (((char *) rec) + 0x30)) = 0x80;\n}\n')
    asm = 'glabel f\n  sb $v0, 0x28($s0)\n  sw $v0, 0x30($s0)\n'
    out = [text for _family, text in nsw.variants(source, 'f', asm=asm)]
    assert len(out) == 1
    assert '*((u8 *) (((char *) rec) + 0x28)) = 0x80;' in out[0]
    assert '*((s32 *) (((char *) rec) + 0x28)) = (s32)' in out[0] and '*((s32 *) (((char *) rec) + 0x30)) = 0x80;' in out[0]
    # a value the byte cannot hold stays a word
    assert nsw.variants(source.replace('= 0x80;\n    *((s32 *) (((char *) rec) + 0x30)) = 0x80;', '= 0x180;\n'), 'f', asm=asm) == []
