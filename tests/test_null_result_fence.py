from decomprepair import null_result_fence, shared_exit_guard_return

SOURCE = '''void *func(void *arg0) {
    u8 temp_v1;
    void *temp_s2;

    temp_s2 = gPlayer;
    if ((temp_s2 != NULL) && (TYPE(temp_s2) != 0xFFFF)) {
        temp_v1 = STATE(temp_s2);
        if (temp_v1 != 0) {
            if (TYPE(arg0) != 0xFFFF) {
                if (touches(arg0, temp_s2)) {
                    TARGET(temp_s2) = arg0;
                    ANGLE(temp_s2) = (u8) ANGLE(arg0);
                    return temp_s2;
                }
                goto block_9;
            }
            goto block_9;
        }
block_9:
        /* shared */
        return NULL;
    }
    return NULL;
}
'''

# the same store through a field, the form the byte temporary takes
FIELDS = SOURCE.replace('ANGLE(temp_s2) =', 'temp_s2->angle =')


def test_result_variable_cleared_before_the_guard():
    children = dict(null_result_fence.variants(SOURCE, 'func'))
    child = children['null_result_fence']
    assert 'void * __repair_result;' in child
    assert ('do { __repair_result = NULL; } while (0);\n    if (temp_s2 != NULL) {\n'
            '        if (TYPE(temp_s2) == 0xFFFF) {\n            return NULL;\n        }\n') in child
    assert '__repair_result = temp_s2;\n                    goto __repair_done;' in child
    assert child.rstrip().endswith('__repair_done:\n    return __repair_result;\n}')


def test_byte_copy_through_the_tested_local():
    child = dict(null_result_fence.variants(FIELDS, 'func'))['null_result_byte_temp']
    assert 's32 temp_v1;' in child
    assert ('temp_v1 = ANGLE(arg0);\n                    __repair_result = temp_s2;\n'
            '                    temp_s2->angle = temp_v1;\n                    goto __repair_done;') in child


def test_shared_exit_written_as_the_early_return():
    [(family, child)] = shared_exit_guard_return.variants(SOURCE, 'func')
    assert family == 'shared_exit_guard_return'
    assert '            if (TYPE(arg0) == 0xFFFF) {\n                return NULL;\n            }\n' in child
    assert '                goto block_9;\n        }\nblock_9:' in child


def test_other_shapes_are_left_alone():
    assert not null_result_fence.variants(SOURCE.replace('temp_s2 != NULL) &&', 'temp_s2 != NULL) ||'), 'func')
    assert not null_result_fence.variants(SOURCE.replace('return temp_s2;', 'return NULL;'), 'func')
    assert not shared_exit_guard_return.variants(SOURCE.replace('        /* shared */\n        return NULL;', '        f();\n        return NULL;'), 'func')
