"""small_data_global_local: a small-data global the target splits, as an incomplete array held in a once-set local."""
from decomprepair import registry
from decomprepair import small_data_global_local as sdl

SOURCE = '''s32 func_800221C0(s32, s32);
void *func_800232B4(s32, s32, s32, s32);
extern s16 D_800BD218;
extern void func_80012228(void);
extern s32 func_8002FBC0;

#define F(p, T, o) (*(T *)((s8 *)(p) + (o)))

void *func_8001230C(void *arg0) {
    void *temp_v0;

    temp_v0 = func_800232B4(1, (s32) F(arg0, f32, 4), (s32) F(arg0, f32, 8), (s32) F(arg0, f32, 0xC));
    F(temp_v0, void *, 0x98) = &func_8002FBC0;
    F(temp_v0, void *, 0x9C) = &func_80012228;
    F(temp_v0, s32, 0x70) = 0x5A;
    F(temp_v0, s32, 0x60) = *(s32 *)&D_800BD218;
    F(temp_v0, s32, 0x58) = func_800221C0(0, 1);
    return temp_v0;
}
'''
ASM = '''glabel func_8001230C
/* 0 80001000 3C0800FF */  lui        $t0, 0xFF
/* 4 80001004 3C028003 */  lui        $v0, %hi(func_8002FBC0)
/* 8 80001008 3C03800C */  lui        $v1, %hi(D_800BD218)
/* C 8000100C AE020098 */  sw         $v0, 0x98($s0)
/* 10 80001010 3C028001 */  lui        $v0, %hi(func_80012228)
/* 14 80001014 8C63D218 */  lw         $v1, %lo(D_800BD218)($v1)
'''
ADJACENT = ASM.replace('/* C 8000100C AE020098 */  sw         $v0, 0x98($s0)\n', '').replace(
    '/* 10 80001010 3C028001 */  lui        $v0, %hi(func_80012228)\n', '')
AT = ASM.replace('lui        $v1, %hi(D_800BD218)', 'lui        $at, %hi(D_800BD218)')
FLAGS = ('-G8', '-mips2', '-O2')


def run(source=SOURCE, asm=ASM, flags=FLAGS, header=''):
    return [child for _, child in sdl.variants(source, 'func_8001230C', header, asm, flags)]


def test_the_cast_read_becomes_an_array_read_and_a_local_at_each_position():
    out = run()
    assert len(out) == 5  # the array, then the read's statement and the three before it, up to the call
    assert 'extern s32 D_800BD218[];' in out[0] and 'F(temp_v0, s32, 0x60) = D_800BD218[0];' in out[0]
    assert 'extern s16' not in out[0]
    local = out[3]  # the 0x9C store's position: just after the 0x98 store, as the match had it
    assert local.index('0x98) = &func_8002FBC0;') < local.index('temp_D_800BD218 = ') < local.index('0x9C)')
    assert 'extern s32 D_800BD218[];' in local and 'extern s16' not in local
    assert 's32 temp_D_800BD218;' in local and 'F(temp_v0, s32, 0x60) = temp_D_800BD218;' in local
    firsts = [child.index('temp_D_800BD218 = D_800BD218[0];') for child in out[1:]]
    stores = [child.index('F(temp_v0, s32, 0x60)') for child in out[1:]]
    assert all(a < b for a, b in zip(firsts, stores)) and len(set(firsts)) == 4
    after_store = [child for child in out[1:]
                   if child.index('0x98) = &func_8002FBC0;') < child.index('temp_D_800BD218 = ')]
    assert len(after_store) == 3  # never above the 0x98 store's predecessor, the call: it may change the global


def test_a_local_is_never_set_above_a_call():
    out = run()
    call = SOURCE.index('func_800232B4(1')
    assert all(child.index('temp_D_800BD218 = ') > child.index('F(arg0, f32, 0xC));') for child in out[1:])
    assert call >= 0


def test_a_plain_read_keeps_the_scalars_own_type():
    source = SOURCE.replace('*(s32 *)&D_800BD218', 'D_800BD218')
    [(_, array), *_] = sdl.variants(source, 'func_8001230C', '', ASM, FLAGS)
    assert 'extern s16 D_800BD218[];' in array and '= D_800BD218[0];' in array


def test_the_gate():
    assert run(asm=ADJACENT) == []          # the lui sits next to its load: nothing to separate
    assert run(asm=AT) == []                # the assembler's own macro ($at)
    assert run(flags=('-G0', '-O2')) == []  # 4 bytes are above -G0
    assert run(flags=('-O2',)) == []        # no -G in the profile
    assert run(asm='') == []
    assert run(header='extern s16 D_800BD218;') == []  # a header names it
    assert run(SOURCE.replace('extern s16', 'extern volatile s16')) == []


def test_other_uses_stop_it():
    assert run(SOURCE.replace('return temp_v0;', 'D_800BD218 = 1;\n    return temp_v0;')) == []
    assert run(SOURCE.replace('return temp_v0;', 'func_800221C0((s32) &D_800BD218, 0);\n    return temp_v0;')) == []
    other = SOURCE + '\nvoid other(void) {\n    D_800BD218 = 2;\n}\n'
    assert run(other) == []


def test_two_reads_get_only_the_array():
    source = SOURCE.replace('F(temp_v0, s32, 0x70) = 0x5A;', 'F(temp_v0, s32, 0x70) = *(s32 *)&D_800BD218;')
    out = run(source)
    assert len(out) == 1 and out[0].count('D_800BD218[0]') == 2


def test_a_read_inside_a_branch_gets_only_the_array():
    source = SOURCE.replace('    F(temp_v0, s32, 0x60) = *(s32 *)&D_800BD218;',
                            '    if (arg0 != 0) {\n        F(temp_v0, s32, 0x60) = *(s32 *)&D_800BD218;\n    }')
    out = run(source)
    assert len(out) == 1 and 'temp_D_800BD218' not in out[0]


def test_it_is_declared():
    repair = next(r for r in registry.declared() if r.module == 'small_data_global_local')
    assert repair.families == (sdl.FAMILY,) and 'flags' in repair.needs and 'asm' in repair.needs
