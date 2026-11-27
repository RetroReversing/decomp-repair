from decomprepair import carried_store_arms_repairs as repairs

SOURCE = '''void func_80000000(void *arg0) {
    u8 var_v0;

    if (M2C_FIELD(arg0, u16 *, 0x6A) == 0xE) {
        func_80001000(arg0);
        var_v0 = 0x96;
    } else {
block_6:
        var_v0 = 0x2D - (M2C_FIELD(arg0, u8 *, 0x37) * 2);
    }
    M2C_FIELD(arg0, u8 *, 0x73) = var_v0;
    M2C_FIELD(arg0, u8 *, 0x72) = var_v0;
    M2C_FIELD(arg0, u8 *, 0x71) = var_v0;
    func_80002000(arg0);
}
'''


def test_run_of_stores_goes_to_both_arms():
    [(family, child)] = repairs.variants(SOURCE, 'func_80000000')
    assert family == repairs.FAMILY
    assert '''        func_80001000(arg0);
        M2C_FIELD(arg0, u8 *, 0x73) = 0x96;
        M2C_FIELD(arg0, u8 *, 0x72) = 0x96;
        M2C_FIELD(arg0, u8 *, 0x71) = 0x96;
    } else {''' in child
    assert '''        var_v0 = 0x2D - (M2C_FIELD(arg0, u8 *, 0x37) * 2);
        M2C_FIELD(arg0, u8 *, 0x73) = var_v0;
        M2C_FIELD(arg0, u8 *, 0x72) = var_v0;
        M2C_FIELD(arg0, u8 *, 0x71) = var_v0;
    }
    func_80002000(arg0);''' in child
    assert 'u8 var_v0;' in child


def test_two_literal_arms_drop_the_variable():
    source = SOURCE.replace('0x2D - (M2C_FIELD(arg0, u8 *, 0x37) * 2)', '5')
    [(_, child)] = repairs.variants(source, 'func_80000000')
    assert 'var_v0' not in child
    assert child.count('= 5;') == 3


def test_literal_the_variable_cannot_hold_stays_in_the_variable():
    source = SOURCE.replace('var_v0 = 0x96;', 'var_v0 = 0x196;')
    [(_, child)] = repairs.variants(source, 'func_80000000')
    assert 'var_v0 = 0x196;' in child
    assert 'M2C_FIELD(arg0, u8 *, 0x73) = 0x196;' not in child


def test_variable_read_after_the_run_is_left_alone():
    source = SOURCE.replace('func_80002000(arg0);', 'func_80002000(var_v0);')
    assert repairs.variants(source, 'func_80000000') == []
