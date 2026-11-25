"""float_literal_global: a float global read only as the literal its word holds, from the caller's data."""
import struct

from decomprepair import float_literal_global as flg
from decomprepair import registry

COMPARE = '''extern f32 D_8000930C;
extern f32 D_801700D0;
s32 check(void *);

void f(void *arg0) {
    f32 temp_fs0;

    temp_fs0 = D_801700D0;
    if ((temp_fs0 < D_8000930C) && (check(arg0) != 0)) {
        *(s32 *)((s8 *)arg0 + 0x64) = 0x64;
    }
}
'''
COMPARE_ASM = '''glabel f
/* 0 80001000 3C028017 */  lui        $v0, %hi(D_801700D0)
/* 4 80001004 C45400D0 */  lwc1       $fs0, %lo(D_801700D0)($v0)
/* 8 80001008 3C018001 */  lui        $at, %hi(D_8000930C)
/* C 8000100C C420930C */  lwc1       $fv0, %lo(D_8000930C)($at)
/* 10 80001010 4600A03C */  c.lt.s     $fs0, $fv0
'''
SUM = '''extern f32 D_80000470;
extern void *D_800BD06C;

void f(void *arg0) {
    *(f32 *)((s8 *)arg0 + 4) = *(f32 *)((s8 *)D_800BD06C + 4);
    *(f32 *)((s8 *)arg0 + 8) = (f32) (*(f32 *)((s8 *)D_800BD06C + 8) + D_80000470);
}
'''
SUM_ASM = '''glabel f
/* 0 80001000 3C02800C */  lui        $v0, %hi(D_800BD06C)
/* 4 80001004 8C43D06C */  lw         $v1, %lo(D_800BD06C)($v0)
/* 8 80001008 3C018000 */  lui        $at, %hi(D_80000470)
/* C 8000100C C4220470 */  lwc1       $fv1, %lo(D_80000470)($at)
'''
FIVE_HUNDRED, HUNDRED = 0x43FA0000, 0x42C80000


def _bits(text):
    return struct.unpack('>I', struct.pack('>f', float(text.strip('()').rstrip('f'))))[0]


def test_a_compare_with_a_float_constant_read_through_a_global_becomes_the_literal():
    out = flg.variants(COMPARE, 'f', asm=COMPARE_ASM, words={'D_8000930C': FIVE_HUNDRED, 'D_801700D0': HUNDRED})
    assert len(out) == 1  # D_801700D0 is a real global: loaded through $v0, not $at
    family, child = out[0]
    assert family == 'float_literal_global'
    assert 'if ((temp_fs0 < 500.0f) && (check(arg0) != 0))' in child
    assert 'temp_fs0 = D_801700D0;' in child


def test_a_sum_with_a_float_constant_becomes_the_literal_and_the_m2c_spelling_too():
    [(_, child)] = flg.variants(SUM, 'f', asm=SUM_ASM, words={'D_80000470': HUNDRED})
    assert '(*(f32 *)((s8 *)D_800BD06C + 8) + 100.0f)' in child
    m2c = SUM.replace('*(f32 *)((s8 *)D_800BD06C + 8)', 'M2C_FIELD(D_800BD06C, f32 *, 8)')
    [(_, child)] = flg.variants(m2c, 'f', asm=SUM_ASM, words={'D_80000470': HUNDRED})
    assert '(M2C_FIELD(D_800BD06C, f32 *, 8) + 100.0f)' in child


def test_two_constants_give_one_child_each_and_one_with_both():
    source = SUM.replace('+ D_80000470);', '+ D_80000470) * D_80000474;').replace(
        'extern f32 D_80000470;', 'extern f32 D_80000470;\nextern float D_80000474;')
    asm = SUM_ASM + '/* 10 80001010 3C018000 */  lui $at, %hi(D_80000474)\n' \
                    '/* 14 80001014 C4200474 */  lwc1 $f0, %lo(D_80000474)($at)\n'
    out = [child for _, child in flg.variants(source, 'f', asm=asm, words={'D_80000470': HUNDRED, 'D_80000474': 0x3F000000})]
    assert len(out) == 3 and '+ 100.0f) * 0.5f;' in out[2]


def test_literals_round_trip_to_the_same_bits():
    for word in (FIVE_HUNDRED, HUNDRED, 0x3DCCCCCD, 0x40490FDB, 0xBF800000, 0x3F000000, 0x4B189680, 0x2F800000):
        text = flg.literal(word)
        assert text and _bits(text) == word, (hex(word), text)
    assert flg.literal(FIVE_HUNDRED) == '500.0f' and flg.literal(0x3DCCCCCD) == '0.1f'
    assert flg.literal(0xBF800000) == '(-1.0f)'


def test_words_that_are_not_plausible_literals_are_refused():
    for word in (0, 0x80000000, 0x8012ABCD, 0x80400000, 0xA4000000, 0x00000064, 0x007FFFFF, 0x7F800000, 0xFF800000,
                 0x7FC00000, 0x6F000000, -1, 1 << 32, None):
        assert flg.literal(word) is None, word
        assert flg.variants(COMPARE, 'f', asm=COMPARE_ASM, words={'D_8000930C': word}) == []


def test_a_global_the_function_writes_or_takes_the_address_of_is_left_alone():
    words = {'D_8000930C': FIVE_HUNDRED}
    for body in ('D_8000930C = temp_fs0;', 'D_8000930C += 1.0f;', 'D_8000930C++;', 'check(&D_8000930C);',
                 '(&D_8000930C)[0] = 1.0f;'):
        source = COMPARE.replace('*(s32 *)((s8 *)arg0 + 0x64) = 0x64;', body)
        assert flg.variants(source, 'f', asm=COMPARE_ASM, words=words) == [], body
    # an address in the target's code (an addiu of %lo, a store) is not a literal read either
    for line in ('addiu $a0, $at, %lo(D_8000930C)', 'swc1 $f0, %lo(D_8000930C)($at)', 'lw $v0, %lo(D_8000930C)($at)'):
        assert flg.variants(COMPARE, 'f', asm=COMPARE_ASM + line + '\n', words=words) == [], line


def test_only_a_plain_float_declaration_and_a_float_load_through_at():
    words = {'D_8000930C': FIVE_HUNDRED}
    for declaration in ('extern f64 D_8000930C;', 'extern double D_8000930C;', 'extern s32 *D_8000930C;', 'extern s32 D_8000930C[2];',
                        'extern f32 *D_8000930C;', 'extern f32 D_8000930C[2];', 'extern volatile f32 D_8000930C;'):
        source = COMPARE.replace('extern f32 D_8000930C;', declaration)
        assert flg.variants(source, 'f', asm=COMPARE_ASM, words=words) == [], declaration
    assert flg.variants(COMPARE.replace('extern f32 D_8000930C;\n', ''), 'f', asm=COMPARE_ASM, words=words) == []
    # declared in the header instead
    header = 'typedef float f32;\nextern float D_8000930C;\n'
    assert flg.variants(COMPARE.replace('extern f32 D_8000930C;\n', ''), 'f', header=header, asm=COMPARE_ASM, words=words)
    real_global = COMPARE_ASM.replace('lui        $at, %hi(D_8000930C)', 'lui        $v1, %hi(D_8000930C)').replace(
        '%lo(D_8000930C)($at)', '%lo(D_8000930C)($v1)')
    assert flg.variants(COMPARE, 'f', asm=real_global, words=words) == []
    gp = COMPARE_ASM.replace('lui        $at, %hi(D_8000930C)', 'nop').replace('%lo(D_8000930C)($at)', '%gp_rel(D_8000930C)($gp)')
    assert flg.variants(COMPARE, 'f', asm=gp, words=words)
    assert flg.variants(COMPARE, 'f', asm='', words=words) == []
    assert flg.variants(COMPARE, 'f', asm=COMPARE_ASM) == []


def test_an_integer_word_the_target_loads_with_lwc1_is_a_float_literal_too():
    """m2c types a pool word by its uses: `temp_f = D_x;` into a float local leaves `extern s32 D_x;`."""
    words = {'D_8000930C': FIVE_HUNDRED}
    for declaration in ('extern s32 D_8000930C;', 'extern u32 D_8000930C;', 'extern M2C_UNK D_8000930C;'):
        source = COMPARE.replace('extern f32 D_8000930C;', declaration)
        [(family, child)] = flg.variants(source, 'f', asm=COMPARE_ASM, words=words)
        assert family == 'float_literal_global' and '(temp_fs0 < 500.0f)' in child, declaration
    # the integer load of an integer word is a real integer global
    integer_load = COMPARE_ASM.replace('lwc1       $fv0, %lo(D_8000930C)($at)', 'lw         $v0, %lo(D_8000930C)($at)')
    source = COMPARE.replace('extern f32 D_8000930C;', 'extern s32 D_8000930C;')
    assert flg.variants(source, 'f', asm=integer_load, words=words) == []


def test_another_function_in_the_source_that_names_it_keeps_it():
    source = COMPARE + '\nf32 g(void) {\n    return D_8000930C;\n}\n'
    assert flg.variants(source, 'f', asm=COMPARE_ASM, words={'D_8000930C': FIVE_HUNDRED}) == []


def test_it_is_declared_with_optional_words_and_an_older_caller_without_them_gets_nothing():
    repair = registry.get('float_literal_global')
    assert repair and registry.problems(repair) == [] and 'words' in repair.needs
    old_context = dict(source=COMPARE, name='f', header='', arch='mips', asm=COMPARE_ASM, flags=())
    assert registry.run('float_literal_global', **old_context) == []
    labelled = registry.run('float_literal_global', **old_context, words={'D_8000930C': FIVE_HUNDRED})
    assert labelled and labelled[0][0] == 'float_literal_global' and '500.0f' in labelled[0][1]


def test_an_optional_context_needs_a_default():
    def variants(source, name, words):
        return []
    variants.__module__ = 'decomprepair.float_literal_global'
    repair = registry._make('float_literal_global', {'families': ('x',), 'variants': variants,
                                                     'needs': ('source', 'name', 'words')})
    assert any('give it a default' in problem for problem in registry.problems(repair))


ABSOLUTE = '''typedef struct Cam { s32 x0; s32 x4; f32 x8; f32 xC; } Cam;
extern Cam *D_800BD06C;

void f(void) {
    Cam *c;

    c = D_800BD06C;
    c->x8 = *(f32 *)0x80009BD0;
    c->xC = *(f32 *)0x80009BD4;
}
'''
ABSOLUTE_ASM = '''glabel f
/* 0 80001000 3C03800C */  lui        $v1, %hi(D_800BD06C)
/* 4 80001004 8C63D06C */  lw         $v1, %lo(D_800BD06C)($v1)
/* 8 80001008 3C018001 */  lui        $at, %hi(D_80009BD0)
/* C 8000100C C4209BD0 */  lwc1       $f0, %lo(D_80009BD0)($at)
/* 10 80001010 3C018001 */  lui        $at, %hi(D_80009BD4)
/* 14 80001014 C4229BD4 */  lwc1       $f2, %lo(D_80009BD4)($at)
'''


def test_a_read_through_the_constant_s_address_becomes_the_literal():
    """`*(f32 *)0x80009BD0`: the pool word read by its address (an agent's spelling when the symbol could not link)."""
    words = {'D_80009BD0': 0x43928000, 'D_80009BD4': 0xC40DC000}  # 293.0f, -567.0f
    out = [s for _, s in flg.variants(ABSOLUTE, 'f', '', ABSOLUTE_ASM, words)]
    assert any('c->x8 = 293.0f;' in s and '0x80009BD4' in s for s in out)
    assert any('c->xC = (-567.0f);' in s and '0x80009BD0' in s for s in out)
    assert any('293.0f' in s and '(-567.0f)' in s and '0x8000' not in s.split('void f')[1] for s in out)


def test_an_address_the_function_writes_through_is_left_alone():
    source = ABSOLUTE.replace('    c->xC = *(f32 *)0x80009BD4;\n', '    *(f32 *)0x80009BD4 = 1.0f;\n')
    out = [s for _, s in flg.variants(source, 'f', '', ABSOLUTE_ASM, {'D_80009BD4': 0xC40DC000})]
    assert out == []


HELD = '''typedef struct Obj { f32 x100; f32 x104; } Obj;
void show(s32);

s32 f(Obj *o) {
    s32 i;
    f32 k;

    k = *(f32 *)0x80008274;
    if (o->x100 > k) {
        show(1);
    }
    if (o->x104 > k) {
        show(2);
    }
    return 0;
}
'''
HELD_ASM = '''glabel f
/* 0 80001000 C6000100 */  lwc1       $f0, 0x100($s0)
/* 4 80001004 3C018001 */  lui        $at, %hi(D_80008274)
/* 8 80001008 C4348274 */  lwc1       $f20, %lo(D_80008274)($at)
'''


def test_a_local_that_only_holds_the_word_is_written_as_the_literal_at_each_use():
    out = [s for _, s in flg.variants(HELD, 'f', '', HELD_ASM, {'D_80008274': 0x3727C5AC})]
    assert any('k = 1e-05f;' in s for s in out)  # the plain child stays
    held = [s for s in out if 'o->x100 > 1e-05f' in s and 'o->x104 > 1e-05f' in s]
    assert held and 'f32 k;' not in held[0] and 'k =' not in held[0] and '    s32 i;\n\n    if' in held[0]


def test_a_local_assigned_again_is_not_a_holder():
    source = HELD.replace('    return 0;', '    k = 2.0f;\n    return 0;')
    out = [s for _, s in flg.variants(source, 'f', '', HELD_ASM, {'D_80008274': 0x3727C5AC})]
    assert out and not any('o->x100 > 1e-05f' in s for s in out)
