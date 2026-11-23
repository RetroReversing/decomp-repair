from decomprepair.real_loop_unreduced import LOOP, STORE, loop_variants, probes, store_variants, variants

SOURCE = """extern u8 gTable[];
extern u8 gCount;
s32 f(s32 a, s32 b) {
    u32 i;
    s32 prev;
    i = 0;
    if (gCount != 0) {
        loop: {
            if (*(s32 *)(gTable + i * 8) != -1) {
                *(s32 *)(gTable + ((prev & 0xFF) * 0x1A0)) = *(s32 *)(gTable + 4);
                prev = i;
            }
            i += 1;
        }
        if (i < (u8) gCount) goto loop;
    }
    return prev;
}
"""


def test_a_labelled_block_closed_by_a_goto_is_written_as_do_while():
    [looped] = loop_variants(SOURCE, 'f')
    assert 'goto' not in looped and 'loop:' not in looped
    assert 'do {' in looped and '} while (i < (u8) gCount);' in looped
    assert looped.count('{') == looped.count('}')


def test_two_gotos_to_one_label_or_a_continue_are_left_alone():
    assert loop_variants(SOURCE.replace('        if (i < (u8) gCount) goto loop;', '        if (i < 3) goto loop;\n        if (i < (u8) gCount) goto loop;'), 'f') == []
    assert loop_variants(SOURCE.replace('i += 1;', 'if (i == 2) continue;\n            i += 1;'), 'f') == []


def test_a_table_store_through_a_symbol_sum_goes_through_a_pointer_local():
    [stored] = store_variants(SOURCE, 'f')
    assert 's32 *store_ptr; store_ptr = (s32 *)(gTable + ((prev & 0xFF) * 0x1A0)); *store_ptr = *(s32 *)(gTable + 4);' in stored
    assert [family for family, _ in variants(SOURCE, 'f')] == [LOOP, STORE]


def test_the_joint_probe_carries_the_profile_without_strength_reduction():
    fn = {'best_source': SOURCE, 'name': 'f', 'asm': '/* 1 */  lui        $at, %hi(gTable)\n/* 2 */  addu       $at, $at, $v1\n/* 3 */  sw $a0, %lo(gTable)($at)'}
    own = {'toolchain': 'gcc-2.7.2-kmc', 'flags': ['-G0', '-mips3', '-O2']}
    [(flags, child)] = probes({'arch': 'mips'}, fn, own)
    assert flags == ['-G0', '-mips3', '-O2', '-fno-strength-reduce']
    assert 'do {' in child and 'store_ptr' in child and 'if (i < gCount)' in child and 'goto' not in child


def test_no_probe_without_the_table_idiom_or_when_the_profile_already_has_it():
    fn = {'best_source': SOURCE, 'name': 'f', 'asm': 'addu $v0, $v0, $v1'}
    own = {'toolchain': 'gcc-2.7.2-kmc', 'flags': ['-O2']}
    assert probes({'arch': 'mips'}, fn, own) == []
    fn['asm'] = 'lui $at, %hi(x)\n addu $at, $at, $v1'
    assert probes({'arch': 'mips'}, fn, dict(own, flags=['-O2', '-fno-strength-reduce'])) == []
    assert probes({'arch': 'mips'}, fn, dict(own, toolchain='ido-7.1')) == []


def test_weight_ladders_are_stripped_from_the_joint_child_only():
    from decomprepair.real_loop_unreduced import strip_weight_ladders
    laddered = SOURCE.replace('    i = 0;', '    do { do { i = 0; } while (0); } while (0);')
    assert 'i = 0;' in strip_weight_ladders(laddered, 'f') and 'while (0)' not in strip_weight_ladders(laddered, 'f')
    fn = {'best_source': laddered, 'name': 'f', 'asm': 'lui $at, %hi(x)\n/* */ addu $at, $at, $v1'}
    [(flags, child)] = probes({'arch': 'mips'}, fn, {'toolchain': 'gcc-2.7.2-kmc', 'flags': ['-O2']})
    assert 'while (0)' not in child and 'while (i <' in child
