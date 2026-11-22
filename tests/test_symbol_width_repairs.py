"""A `char` symbol's accesses at the width the target's own instructions use."""
from decomprepair import symbol_width_repairs as w

SOURCE = '''extern char D_8010D784[];
extern char D_8010D7E1[];

void f(s32 arg0, s32 off) {
    *(D_8010D784 + off) = arg0;
    *(D_8010D7E1 + off) = 0;
}
'''
ASM = '''/* 9A1FC 800995FC AC30D784 */  sw         $s0, %lo(D_8010D784)($at)
/* 9A2F0 800996F0 A020D7E1 */  sb         $zero, %lo(D_8010D7E1)($at)
'''


def test_word_store_from_the_target():
    # An N64 function stored a word where m2c's char array gave `sb`.
    (family, out), = w.variants(SOURCE, 'f', ASM)
    assert family == 'symbol_access_width'
    assert '*(s32 *)(D_8010D784 + off) = arg0;' in out and '*(D_8010D7E1 + off) = 0;' in out


def test_widths():
    assert w.widths('lhu $v0, %lo(D_1)($v0)\nsh $v0, %lo(D_1)($at)', 'D_1') == {'u16', 's16'}
    out = w.variants(SOURCE, 'f', 'lhu $v0, %lo(D_8010D784)($v0)\nsh $v0, %lo(D_8010D784)($at)')[0][1]
    assert '*(u16 *)(D_8010D784 + off)' in out


def test_left_alone():
    assert w.variants(SOURCE, 'f', '') == []
    # mixed widths, or bytes too: no single answer
    assert w.variants(SOURCE, 'f', ASM.replace('sb         $zero, %lo(D_8010D7E1)', 'sb  $zero, %lo(D_8010D784)')) == []
    assert w.variants(SOURCE, 'f', ASM + 'lh $v0, %lo(D_8010D784)($v0)\n') == []
    # a symbol of known type is not touched
    assert w.variants(SOURCE.replace('extern char D_8010D784[];', 'extern s32 D_8010D784;'), 'f', ASM) == []


UNKNOWN = '''s16 f(s32 arg0) {
    u32 i;

    i = arg0 & 0xFFF;
    if (i < 0x400U) {
        return *((M2C_UNK *)((s8 *)&D_800CF554 + (i * 2)));
    }
    if (i < 0x800U) {
        return *((M2C_UNK *)((s8 *)&D_800CF554 + ((~arg0 & 0x3FF) * 2)));
    }
    return (s16) ((s32) *((M2C_UNK *)((s8 *)&D_800CF554 + ((arg0 & 0x3FF) * 2))) * -1);
}
'''
UNKNOWN_ASM = '''lh         $v0, %lo(D_800CF554)($at)
lh         $v0, %lo(D_800CF554)($at)
lhu        $v0, %lo(D_800CF554)($at)
'''


def test_m2c_word_casts_take_the_targets_widths():
    # An N64 sine table: 92% read as words; exact with each read as the target's (lh, lh, lhu).
    (family, ordered), (_, common) = w.variants(UNKNOWN, 'f', UNKNOWN_ASM)
    assert family == 'symbol_access_width'
    assert ordered.count('(s16 *)((s8 *)&D_800CF554') == 2 and ordered.count('(u16 *)((s8 *)&D_800CF554') == 1
    assert ordered.index('(u16 *)') > ordered.rindex('(s16 *)((s8')
    assert common.count('(s16 *)((s8 *)&D_800CF554') == 3
    assert w.variants(UNKNOWN, 'f', UNKNOWN_ASM.replace('lh ', 'lw ').replace('lhu', 'lw ')) == []


TYPED = '''extern s32 gFlags;

void f(void *arg0, u16 i) {
    u8 v;
    v = *((s32 *) (((s8 *) (&gFlags)) + i));
    if (v < 2U) {
        *((s32 *) (((s8 *) (&gFlags)) + i)) = v ^ 1;
    }
}
'''


def test_wrong_width_cast_on_a_typed_symbol():
    # The printed dialect (extra parentheses), a concrete `s32` symbol: the target's loads were `lbu`/`sb`.
    asm = 'lbu $v1, %lo(gFlags)($v1)\nsb $v0, %lo(gFlags)($at)\n'
    outs = [out for _, out in w.variants(TYPED, 'f', asm)]
    assert outs and '*((u8 *) (((s8 *) (&gFlags)) + i))' in outs[0] and '(s32 *)' not in outs[0]
    # accesses the cast already matches are left alone
    assert w.variants(TYPED, 'f', 'lw $v1, %lo(gFlags)($v1)\nsw $v0, %lo(gFlags)($at)\n') == []


def test_measured_signed_halfword_load_preserves_its_relocation():
    from decomprepair.symbol_width_repairs import signed_halfword_load_variants

    source = """extern s8 fields[];
void f(void) {
    s32 i = 0;
    s16 *cursor = values;
    s32 index = 0, dest = 0;
    do {
        s32 value;
        value = *(volatile s32 *)(fields + index);
        publish(value);
        index += 8;
    } while (++i < 4);
}
"""
    rows = [('|', 'lh $v0, %lo(fields)($v0)', 'lw $v0, %lo(fields)($v0)')]
    [(family, reordered), (_, staged), (_, qualified)] = signed_halfword_load_variants(source, 'f', rows)
    assert family == 'relocated_signed_halfword_load'
    assert 's32 index = 0; s16 *cursor = values; s32 i = 0;' in reordered
    assert 'do { value = *(s16 *)(fields + index); } while (0);' in staged
    assert 'value = *(volatile s16 *)(fields + index);' in qualified
    assert not signed_halfword_load_variants(source, 'f', [('|', rows[0][1], rows[0][2].replace('fields', 'other'))])
    assert not signed_halfword_load_variants(source.replace('value = *', 'if (flag) value = *'), 'f', rows)


def test_measured_halfword_update_requires_both_accesses():
    source = '''extern char fields[];
void f(int i) {
    *(fields + i) = *(fields + i) & 0xFFEF;
}
'''
    target = 'lhu $v1, %lo(fields)($v1)\nsh $v1, %lo(fields)($at)'
    rows = [('|', 'lhu $v1, %lo(fields)($v1)', 'lbu $v1, %lo(fields)($v1)'),
            ('|', 'sh $v1, %lo(fields)($at)', 'sb $v1, %lo(fields)($at)')]
    (family, result), = w.measured_halfword_update_variants(source, 'f', '', target, rows)
    assert family == 'symbol_access_width'
    assert result.count('*(u16 *)(fields + i)') == 2
    assert not w.measured_halfword_update_variants(source, 'f', '', target, rows[:1])
    assert not w.measured_halfword_update_variants(source, 'f', '#define fields get()', target, rows)
    assert not w.measured_halfword_update_variants(source.replace('int i)', 'int i, char *fields)'), 'f', '', target, rows)
    assert not w.measured_halfword_update_variants(source, 'f', '', target + '\nlbu $v0, %lo(fields)($v0)', rows)
