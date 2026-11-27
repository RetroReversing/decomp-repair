from decomprepair import float_value_stage

SOURCE = '''void func(s32 i, f32 best)
{
    if (best < 0.0f) {
        send(6, i, TABLE[i].vol * (1000.0f - best) / 1000.0f);
    } else if (best < 900.0f) {
        OUT = TABLE[i].vol * (1000.0f - best) / 1000.0f;
    }
}
'''


def test_every_site_shares_one_new_local():
    children = [source for _, source in float_value_stage.variants(SOURCE, 'func')]
    assert len(children) == 3
    together = children[-1]
    assert together.count('staged_value = TABLE[i].vol * (1000.0f - best) / 1000.0f;') == 2
    assert 'send(6, i, staged_value);' in together
    assert 'OUT = staged_value;' in together
    assert together.count('f32 staged_value;') == 1


def test_one_site_at_a_time():
    first, second, _ = [source for _, source in float_value_stage.variants(SOURCE, 'func')]
    assert 'send(6, i, staged_value);' in first and 'OUT = TABLE[i]' in first
    assert 'OUT = staged_value;' in second and 'send(6, i, TABLE[i]' in second


def test_float_destinations_doubles_and_volatile_are_left_alone():
    assert not float_value_stage.variants('void func(f32 a) { f32 x; x = a * 2.0f; }\n', 'func')
    assert not float_value_stage.variants('void func(f32 a) { OUT = a * 2.0; }\n', 'func')
    assert not float_value_stage.variants('void func(f32 a) { volatile s32 v; OUT = a * 2.0f; }\n', 'func')
    assert not float_value_stage.variants('void func(f32 a) { send(next(), a * 2.0f); }\n', 'func')


def test_name_is_not_reused():
    source = 'void func(f32 a) { s32 staged_value; OUT = a * 2.0f; }\n'
    (_, child), = float_value_stage.variants(source, 'func')
    assert 'f32 staged_value2;' in child and 'OUT = staged_value2;' in child
