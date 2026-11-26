from decomprepair import case_pointer_prefetch, low_field_step

SOURCE = '''void f(s32 arg0) {
    u16 temp_v0;
    u16 state;
    void *obj;
    void *car;

    obj = table + arg0;
    car = cars + arg0;
    state = obj_state[arg0];
    switch (state) {
    case 0:
        break;
    case 2:
        (*(s32 *)((char *)((*(void * *)((char *)(obj) + 0x50))) + 4)) = 0;
        temp_v0 = (*(u16 *)((char *)(car) + 0x560));
        (*(u16 *)((char *)(car) + 0x560)) = (u16) ((temp_v0 & 0xF8) | ((temp_v0 & 7) - 1));
        break;
    }
}
'''


def test_the_arms_pointer_is_read_before_the_dispatch():
    children = [text for family, text in case_pointer_prefetch.variants(SOURCE, 'f')]
    assert len(children) == 2
    for text in children:
        assert 'void * __repair_prefetch;' in text
        assert text.index('__repair_prefetch = *(void * *)') < text.index('switch (state)')
        assert '((char *)((__repair_prefetch)) + 4)) = 0;' in text
    assert children[1].index('__repair_prefetch = ') < children[1].index('state = obj_state')


def test_m2c_field_spelling():
    source = SOURCE.replace('(*(void * *)((char *)(obj) + 0x50))', 'M2C_FIELD(obj, void **, 0x50)')
    assert '__repair_prefetch = M2C_FIELD(obj, void **, 0x50);' in case_pointer_prefetch.variants(source, 'f')[0][1]


def test_a_base_the_switch_assigns_is_left_alone():
    assert not case_pointer_prefetch.variants(SOURCE.replace('    case 0:\n', '    case 0:\n        obj = 0;\n'), 'f')


def test_the_low_field_is_read_first():
    ((family, text),) = low_field_step.variants(SOURCE, 'f')
    assert 'temp_v0 = (*(u16 *)((char *)(car) + 0x560)) & 7;\n' in text
    assert '= (u16) (((*(u16 *)((char *)(car) + 0x560)) & 0xF8) | (temp_v0 - 1));' in text


def test_a_value_read_later_is_left_alone():
    assert not low_field_step.variants(SOURCE.replace('        break;\n    }', '        use(temp_v0);\n    }'), 'f')


def test_an_inline_read_gets_the_field_local():
    field = '(*(u16 *)((char *)(car) + 0x560))'
    source = SOURCE.replace(f'temp_v0 = {field};\n        ', '').replace(
        '(temp_v0 & 0xF8) | ((temp_v0 & 7) - 1)', f'(({field}) & 0xF8) | ((({field}) & 7) - 1)')
    ((family, text),) = low_field_step.variants(source, 'f')
    assert 'u16 __repair_low;' in text
    assert f'__repair_low = {field} & 7;\n' in text
    assert f'{field} = (u16) (({field} & 0xF8) | (__repair_low - 1));' in text
