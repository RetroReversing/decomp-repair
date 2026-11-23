from decomprepair.sibling_symbol_offset_read import FAMILY, variants

SOURCE = """extern s32 gVisibleCount;
extern s32 gTotalSlots;
void rank(s32 index) {
    volatile s32 *count = &gVisibleCount;
    s32 temp;
    s32 rank;
    if (index < *count) {
        rank = gTotalSlots;
        temp = 0;
        do {
            rank -= temp != index;
            temp++;
        } while (temp < gTotalSlots);
        use(rank);
    }
}
"""
ASM = """addiu      $sp, $sp, -0x18
lui        $t0, %hi(gVisibleCount)
addiu      $t0, $t0, %lo(gVisibleCount)
lw         $v0, 0x0($t0)
blez       $a2, .L1
lw         $t0, -0xC($t0)
"""


def _children(source=SOURCE, asm=ASM):
    return [child for family, child in variants(source, 'rank', asm) if family == FAMILY]


def test_the_bound_is_read_at_the_top_of_the_body_through_the_neighbours_address():
    children = _children()
    assert len(children) == 1
    child = children[0]
    assert 'limit = ((s32 *) &gVisibleCount)[-3];' in child
    assert 'while (temp < limit);' in child
    assert child.index('do {') < child.index('limit = ') < child.index('rank -=')
    assert 's32 limit;' in child and child.index('s32 limit;') < child.index('if (index < *count)')
    assert 'rank = gTotalSlots;' in child  # the first read of the global stays


def test_no_assembly_or_no_negative_load_off_a_symbol_base_gives_nothing():
    assert variants(SOURCE, 'rank', '') == []
    assert _children(asm=ASM.replace('-0xC($t0)', '0xC($t0)')) == []
    assert _children(asm=ASM.replace('addiu      $t0, $t0, %lo(gVisibleCount)\n', '')) == []
    clobbered = ASM.replace('lw         $t0, -0xC', 'lw         $t1, -0xC').replace('lw         $v0, 0x0($t0)', 'lw         $t0, 0x0($t0)')
    assert _children(asm=clobbered) == []


def test_a_global_of_another_width_is_not_offered():
    assert _children(SOURCE.replace('extern s32 gTotalSlots;', 'extern s16 gTotalSlots;')) == []
    assert _children(asm=ASM.replace('lw         $t0, -0xC', 'lh         $t0, -0xC')) == []


def test_a_bound_that_the_body_also_reads_or_a_loop_that_is_not_a_do_while_is_left_alone():
    assert _children(SOURCE.replace('rank -= temp != index;', 'rank -= gTotalSlots;')) == []
    plain = SOURCE.replace('do {', 'while (temp < gTotalSlots) {').replace('} while (temp < gTotalSlots);', '}')
    assert _children(plain) == []


def test_the_new_local_does_not_take_a_name_the_function_uses():
    child = _children(SOURCE.replace('s32 rank;', 's32 rank;\n    s32 limit;'))[0]
    assert 'limit_ = ((s32 *) &gVisibleCount)[-3];' in child and 'while (temp < limit_);' in child
