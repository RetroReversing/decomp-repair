from decomprepair import indexed_symbol_records as records

DRAFT = '''typedef int M2C_UNK;
extern M2C_UNK D_80100000;
extern M2C_UNK D_80100002;
extern M2C_UNK D_80100008;

void f(void) {
    s32 temp_s0;
    s32 temp_v0;
    u16 i;
    u16 j;

    for (i = 0; i < 7; i++) {
        temp_s0 = i * 0x20;
        g(temp_s0 + &D_80100000);
        *(&D_80100000 + temp_s0) = i;
        *(&D_80100002 + temp_s0) = 0;
        for (j = 0; j < 3; j++) {
            temp_v0 = (j * 8) + (i * 0x20);
            *(&D_80100008 + temp_v0) = 0;
            *(&D_80100008 + 4 + temp_v0) = 0;
        }
    }
}
'''
ASM = '''
    sh         $s1, %lo(D_80100000)($at)
    sh         $zero, %lo(D_80100002)($at)
    sw         $zero, %lo(D_80100008)($at)
    sw         $zero, %lo(D_80100008 + 0x4)($at)
'''


def test_tables_indexed_by_a_product_become_one_record_array():
    [(family, out)] = records.variants(DRAFT, 'f', '', ASM)
    assert family == 'indexed_symbol_records'
    assert 'extern IndexedRow D_80100000[];' in out
    assert 'g(&D_80100000[i]);' in out
    assert 'D_80100000[i].m0 = i;' in out
    assert 'D_80100000[i].m2 = 0;' in out
    assert 'D_80100000[i].m8[j].m0 = 0;' in out
    assert 'D_80100000[i].m8[j].m4 = 0;' in out
    assert 's32 m4;' in out and 's16 m2;' in out and 'm8[3];' in out
    assert 'D_80100002' not in out and 'temp_s0' not in out and 'temp_v0' not in out


def test_casted_accesses_are_read_without_the_assembly():
    source = '''extern char D_80100000[];
void f(s32 i) {
    *(s16 *)(D_80100000 + (i * 0x10)) = 1;
    *(s32 *)((u8 *)&D_80100000 + 4 + (i * 0x10)) = 2;
    *((u8 *) (((u8 *) (&D_80100000)) + (i * 0x10) + 8)) = 3;
}
'''
    [(_, out)] = records.variants(source, 'f')
    assert 'D_80100000[i].m0 = 1;' in out and 'D_80100000[i].m4 = 2;' in out and 'D_80100000[i].m8 = 3;' in out


def test_declines_what_it_does_not_understand():
    # no width from either the assembly or a cast
    assert records.variants(DRAFT, 'f') == []
    # another use of one of the symbols
    assert records.variants(DRAFT.replace('g(temp_s0 + &D_80100000);', 'g(&D_80100002);'), 'f', '', ASM) == []
    # two record sizes
    assert records.variants(DRAFT.replace('temp_s0 = i * 0x20;', 'temp_s0 = i * 0x6;'), 'f', '', ASM) == []
    # a symbol the header declares
    assert records.variants(DRAFT, 'f', 'extern s16 D_80100002;', ASM) == []


CARRIED = '''extern u16 D_80200000[];
extern s8 D_80100000;
extern s8 D_80100002;
extern s8 D_80100006;
extern s8 D_80100028;

void f(void) {
    s32 temp_v0;
    s32 i;
    s32 j;
    s32 off;

    j = 0;
    do {
        temp_v0 = j * 0x70;
        *(&D_80100000 + temp_v0) = 0;
        *(&D_80100002 + temp_v0) = 0;
        i = 0;
        off = 0 * 2;
loop_2:
        *(off + ((j * 0x70) + &D_80100006)) = *(off + D_80200000);
        i += 1;
        off = i * 2;
        if (i < 0x10) {
            goto loop_2;
        }
        *(&D_80100028 + temp_v0) = 0;
        j += 1;
    } while (j < 4);
}
'''
CARRIED_ASM = '''
    sh         $zero, %lo(D_80100000)($at)
    sb         $zero, %lo(D_80100002)($at)
    sw         $zero, %lo(D_80100028)($at)
'''


def test_a_carried_byte_offset_and_another_table():
    [(_, out)] = records.variants(CARRIED, 'f', '', CARRIED_ASM)
    assert 's16 m6[' in out
    assert 'D_80100000[j].m6[i] = D_80200000[i];' in out
    assert 'D_80100000[j].m28 = 0;' in out
    assert 'off' not in out and 'temp_v0' not in out
    assert 'loop_2:' in out


def test_a_table_inside_the_record_that_no_record_index_reaches_is_declined():
    inside = CARRIED.replace('*(off + D_80200000)', '*(off + D_80100010)').replace(
        'extern u16 D_80200000[];', 'extern u16 D_80100010[];')
    assert records.variants(inside, 'f', '', CARRIED_ASM) == []


def test_a_table_read_from_a_byte_inside_its_first_word_starts_at_that_word():
    source = '''typedef int M2C_UNK;
extern M2C_UNK D_80100001;
extern M2C_UNK D_80100010;
extern M2C_UNK D_80100018;

void f(void) {
    s32 off;
    u16 i;

    off = i * 0x64;
    if (*(&D_80100001 + off) == 2) {
        *(&D_80100018 + off) = 0;
    }
    i = *(&D_80100010 + off);
}
'''
    asm = '''
    lbu        $v0, %lo(D_80100001)($at)
    lhu        $a1, %lo(D_80100010)($at)
    swc1       $f0, %lo(D_80100018)($at)
'''
    [(_, out)] = records.variants(source, 'f', '', asm)
    assert 'extern IndexedRow D_80100000[];' in out
    assert 'D_80100000[i].m1 == 2' in out and 'D_80100000[i].m18 = 0;' in out and 'i = D_80100000[i].m10;' in out
    assert 'u8 m1;' in out and 'u16 m10;' in out and 'f32 m18;' in out


def test_declines_members_that_no_record_base_can_align():
    source = '''extern char D_80100000[];
void f(s32 i) {
    *(s16 *)(D_80100000 + (i * 0x10)) = 1;
    *(s32 *)(D_80100000 + (i * 0x10) + 6) = 2;
    *(s32 *)(D_80100000 + (i * 0x10) + 8) = 3;
}
'''
    assert records.variants(source, 'f') == []
