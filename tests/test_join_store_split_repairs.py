from decomprepair import join_store_split_repairs as repair

M2C = '''void f(void) {
    s32 var_s1;
    var_s1 = g_ptr + 0x28;
    switch (gSceneType) {
    case 3:
        if (menuItemIsActive(0x21) & 0xFF) {
            var_s1 = gSceneType; var_s1 += 1;
        } else {
block_12:
            var_s1 = gSceneType - 1;
        }
block_13:
        gSceneType = var_s1;
        func();
        break;
    case 5:
        if (menuItemIsActive(0x21) & 0xFF) {
            var_s1 = gSceneType + 1;
        } else {
            goto block_12;
        }
        goto block_13;
    }
}
'''


def test_the_update_is_stored_on_each_arm():
    out = repair.variants(M2C, 'f')[0]
    assert 'gSceneType = gSceneType + 1;' in out
    assert 'gSceneType = gSceneType - 1;' in out
    assert 'gSceneType = var_s1;' not in out
    assert 'var_s1 = g_ptr + 0x28;' in out
    assert 'block_13:' in out


def test_a_temporary_read_after_the_store_is_left_alone():
    source = M2C.replace('        func();', '        use(var_s1);')
    assert repair.variants(source, 'f') == []


def test_one_feed_is_no_join():
    source = '''void f(void) {
    s32 t;
    t = gX + 1;
    gX = t;
}
'''
    assert repair.variants(source, 'f') == []


def test_an_arm_that_jumps_to_the_join_stores_directly_too():
    out = repair.variants(M2C, 'f')[0]
    assert 'var_s1 = gSceneType + 1;' not in out
    assert out.count('gSceneType = gSceneType + 1;') == 2
    assert out.count('func();') == 2 and 'goto' not in out
