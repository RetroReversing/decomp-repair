from decomprepair import global_byte_run_struct as repair

SOURCE = '''extern signed char D_80001230;
extern signed char D_80001231;
extern signed char D_80001232;
void tint(s32);

void drawTinted(void) {
    s8 sp18;
    s8 sp19;
    s8 sp1A;

    sp18 = D_80001230;
    sp19 = D_80001231;
    sp1A = D_80001232;
    tint((s32) &sp18);
}
'''


def test_copies_the_record_whole():
    [(family, child)] = repair.variants(SOURCE, 'drawTinted')
    assert family == repair.FAMILY
    assert 'typedef struct { s8 f0; s8 f1; s8 f2; } __repair_run3;' in child
    assert 'extern __repair_run3 D_80001230;' in child
    assert '    __repair_run3 sp18;\n\n    sp18 = D_80001230;\n    tint((s32) &sp18);' in child


def test_needs_matching_types_and_consecutive_addresses():
    assert repair.variants(SOURCE.replace('s8 sp19;', 'u8 sp19;'), 'drawTinted') == []
    assert repair.variants(SOURCE.replace('D_80001232', 'D_80001234'), 'drawTinted') == []


def test_leaves_a_later_local_that_is_used_again():
    source = SOURCE.replace('tint((s32) &sp18);', 'tint((s32) &sp18 + sp19);')
    assert repair.variants(source, 'drawTinted') == []


def test_a_following_copy_into_a_word_is_not_part_of_the_record():
    source = SOURCE.replace('    s8 sp1A;\n', '    s8 sp1A;\n    s32 index;\n')
    source = source.replace('    sp1A = D_80001232;\n', '    sp1A = D_80001232;\n    index = D_80005000;\n')
    [(_, child)] = repair.variants(source, 'drawTinted')
    assert '    sp18 = D_80001230;\n    index = D_80005000;\n' in child
