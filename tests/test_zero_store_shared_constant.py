"""A store of 0 offered as the constant the target shares between its other stores."""
from decomprepair import zero_store_shared_constant as r

SOURCE = '''extern s16 gA;
extern s8 gB;
extern s8 *gRec;

void f(void) {
    s32 keep;

    gA = 0;
    gB = 1;
    *((s8 *) (gRec + 0x70)) = 0;
    keep = 0;
    *((s8 *) (gRec + 0x6F)) = 3;
}
'''
ASM = '''addiu      $sp, $sp, -0x18
sh         $zero, %lo(gA)($at)
addiu      $a0, $zero, 0x1
sb         $a0, %lo(gB)($at)
sb         $a0, 0x70($v0)
addiu      $v0, $zero, 0x3
sb         $v0, 0x6F($v1)
'''


def test_target_stores_are_counted_per_register_constant():
    assert r.target_stores(ASM) == (1, {1: 2, 3: 1})
    # a register written in between no longer holds its constant
    assert r.target_stores('addiu $a0, $zero, 1\naddu $a0, $a1, $a2\nsb $a0, 0($v0)\n') == (0, {})


def test_each_zero_store_is_offered_as_the_shared_constant():
    out = [t for _, t in r.variants(SOURCE, 'f', ASM)]
    assert len(out) == 2
    assert 'gA = 1;' in out[0] and '+ 0x70)) = 0;' in out[0]
    assert 'gA = 0;' in out[1] and '+ 0x70)) = 1;' in out[1]
    assert all('keep = 0;' in t for t in out)  # (a plain local is no store to a location)


def test_nothing_when_the_counts_agree_or_there_is_no_target():
    assert r.variants(SOURCE, 'f', '') == []
    assert r.variants(SOURCE, 'f', ASM.replace('sb         $a0, 0x70($v0)\n', 'sb         $zero, 0x70($v0)\n')) == []
    assert r.variants(SOURCE.replace('*((s8 *) (gRec + 0x70)) = 0;', '*((s8 *) (gRec + 0x70)) = 1;'), 'f', ASM) == []


def test_it_declares_itself():
    assert r.REPAIR['families'] == ('zero_store_shared_constant',)
