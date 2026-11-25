"""stored_field_readback_index: a table read at the number just stored into a field, written with the field."""
from decomprepair import registry
from decomprepair import stored_field_readback_index as sfri

SOURCE = '''typedef struct Obj { s32 x70; s32 x74; f32 xB0; f32 xAC; } Obj;
extern Obj *D_800B3960;
extern s32 D_8014A928[];
void func_80082D00(Obj *arg0) {
    s32 t;

    D_800B3960->x74 = 0;
    D_800B3960->x70 = 1;
    D_800B3960->xB0 = D_8014A928[1] / 2;
    D_800B3960->xAC = D_8014A928[1] / 2;
}
'''
NAME = 'func_80082D00'


def children(source=SOURCE):
    return [child for _, child in sfri.variants(source, NAME)]


def test_each_later_read_of_the_stored_number_and_all_of_them_are_children():
    out = children()
    assert len(out) == 3
    assert 'xB0 = D_8014A928[D_800B3960->x70] / 2;' in out[0] and 'xAC = D_8014A928[1] / 2;' in out[0]
    assert 'xAC = D_8014A928[D_800B3960->x70] / 2;' in out[1] and 'xB0 = D_8014A928[1] / 2;' in out[1]
    assert out[2].count('D_8014A928[D_800B3960->x70]') == 2 and 'x70 = 1;' in out[2]


def test_the_m2c_spellings_of_the_field_and_the_byte_offset_are_read():
    source = '''void func_80082D00(void *arg0) {
    M2C_FIELD(arg0, s32 *, 0x70) = 1;
    M2C_FIELD(arg0, f32 *, 0xB4) = (f32) 1.0f;
    M2C_FIELD(arg0, f32 *, 0xB0) = (f32) ((s32) *((1 * 4) + &D_8014A928) / 2);
}
'''
    out = children(source)
    assert len(out) == 1
    assert '*((M2C_FIELD(arg0, s32 *, 0x70) * 4) + &D_8014A928)' in out[0]
    assert children(source.replace('s32 *, 0x70', 'f32 *, 0x70')) == []  # the field is not an integer


def test_a_local_holding_the_stored_value_is_read_back_from_the_field():
    source = '''void func_80082D00(Obj *arg0, s32 e) {
    s32 t;

    t = e + 1;
    arg0->x70 = t;
    arg0->x74 = 0;
    arg0->xB0 = D_8014A928[t];
}
'''
    out = children(source)
    assert len(out) == 1 and 'D_8014A928[arg0->x70]' in out[0]


def test_nothing_between_the_store_and_the_read_may_change_the_field():
    assert children(SOURCE.replace('D_800B3960->xB0 =', 'func(0);\n    D_800B3960->xB0 =')) == []  # a call
    assert children(SOURCE.replace('D_800B3960->x74 = 0;\n    D_800B3960->x70 = 1;',
                                   'D_800B3960->x70 = 1;\n    D_800B3960->x70 = 2;')) == []  # the field stored again
    assert children(SOURCE.replace('D_800B3960->xB0 =', 'arg0->x74 = 3;\n    D_800B3960->xB0 =')) == []  # another base: may alias
    assert children(SOURCE.replace('D_800B3960->xB0 =', 'D_800B3960 = arg0;\n    D_800B3960->xB0 =')) == []  # the base moves
    assert children(SOURCE.replace('D_8014A928[1] / 2;\n    D_800B3960->xAC', 'D_8014A928[2] / 2;\n    D_800B3960->xAC')
                    .replace('D_8014A928[1] / 2;\n}', 'D_8014A928[2] / 2;\n}')) == []  # another number
    assert children(SOURCE.replace('x70 = 1;', 'x70 = 70000;').replace('[1]', '[70000]')) == []


def test_a_store_to_a_local_between_is_harmless_and_a_store_to_the_field_in_the_read_statement_is_not_a_use():
    assert len(children(SOURCE.replace('D_800B3960->xB0 =', 't = 4;\n    D_800B3960->xB0 ='))) == 3
    assert children(SOURCE.replace('D_800B3960->xB0 = D_8014A928[1] / 2;', 'D_800B3960->x70 = D_8014A928[1];')
                    .replace('D_800B3960->xAC = D_8014A928[1] / 2;', '')) == []


def test_it_is_registered():
    repair = {r.module: r for r in registry.declared()}['stored_field_readback_index']
    assert not registry.problems(repair) and repair.families == sfri.FAMILIES
