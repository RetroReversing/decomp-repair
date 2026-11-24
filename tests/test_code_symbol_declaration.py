"""A code symbol m2c declared as data, used only through its address, declared as the function it is."""
from decomprepair import registry
from decomprepair.code_symbol_declaration import FAMILY, OFFSET_FAMILY, variants

# An N64 constructor storing a callback address into a field (SN compiler -O2 -mips2): the draft's declaration.
CALLBACK = '''typedef s32 M2C_UNK;
extern f32 D_80000474;
extern M2C_UNK func_800393F4;

s32 f(void) {
    void *temp_v0;

    temp_v0 = func_80042F00(1, 0, 0, 0);
    M2C_FIELD(temp_v0, void (**)(void), 0x9C) = &func_800393F4;
    M2C_FIELD(temp_v0, f32 *, 8) = D_80000474;
    return (s32) temp_v0;
}
'''

TWO = '''extern M2C_UNK func_80023078;
extern s32 func_80024000;
extern M2C_UNK D_80100000;

void f(void) {
    g(&func_80023078 + 8);
    h((s32)&func_80024000);
    k(&D_80100000);
}
'''


def _children(text, family=None):
    return [src for fam, src in variants(text, 'f') if family in (None, fam)]


def test_an_address_only_symbol_is_declared_as_a_function():
    assert _children(CALLBACK, FAMILY) == [CALLBACK.replace('extern M2C_UNK func_800393F4;', 'extern void func_800393F4(void);')]
    assert _children(CALLBACK, OFFSET_FAMILY) == []  # no offset: no second form


def test_each_symbol_alone_then_all_together_and_a_data_symbol_is_left():
    kids = _children(TWO, FAMILY)
    assert len(kids) == 3
    assert kids[0].count('extern void') == 1 and 'extern void func_80023078(void);' in kids[0]
    assert 'extern void func_80024000(void);' in kids[1]
    assert kids[2].count('extern void') == 2
    assert all('extern M2C_UNK D_80100000;' in kid for kid in kids)


def test_a_constant_offset_is_written_as_bytes():
    kids = _children(TWO, OFFSET_FAMILY)
    assert any('g(((s8 *)&func_80023078 + 8));' in kid and 'extern void func_80023078(void);' in kid for kid in kids)
    assert all('((s8 *)&func_80024000' not in kid for kid in kids)


def test_a_read_a_call_or_an_index_keeps_the_declaration():
    for use in ('x = func_800393F4;', 'func_800393F4(1);', 'x = func_800393F4[2];', 'x = *&func_800393F4;', 'x = p->func_800393F4;'):
        source = CALLBACK.replace('    return', f'    {use}\n    return')
        assert _children(source) == [], use


def test_an_array_symbol_may_be_used_by_its_bare_name():
    source = CALLBACK.replace('extern M2C_UNK func_800393F4;', 'extern u8 func_800393F4[];').replace('&func_800393F4', 'func_800393F4')
    assert len(_children(source, FAMILY)) == 1


def test_only_names_known_as_code_qualify():
    source = CALLBACK.replace('func_800393F4', 'D_800393F4')
    assert _children(source) == []
    assert len(_children(source, FAMILY) + [s for f, s in variants(source, 'f', callees='int D_800393F4(void) { return 0; }') if f == FAMILY]) == 1


def test_it_declares_itself():
    repair = registry.get('code_symbol_declaration')
    assert repair and registry.problems(repair) == []
    assert set(repair.families) == {FAMILY, OFFSET_FAMILY}
