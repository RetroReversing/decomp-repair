from decomprepair import returned_gfx_cursor

SOURCE = '''void *g(void *, s32); /* extern */

void f(void *arg0, s32 arg1, s32 arg2, s32 arg3) {
    void *temp_a0;

    temp_a0 = arg0 + 8;
    M2C_FIELD(arg0, s32 *, 0) = 0xE1000000;
    M2C_FIELD(arg0, s32 *, 4) = arg3;
    M2C_FIELD(arg0, s32 *, 8) = 0xDD0007FF;
    M2C_FIELD(temp_a0, s32 *, 4) = arg2;
    g(temp_a0 + 8, arg1);
}
'''


def test_the_handed_on_cursor_is_written_with_one_shared_command_pointer():
    children = dict(returned_gfx_cursor.variants(SOURCE, 'f'))
    assert list(children) == ['returned_gfx_cursor', 'shared_gfx_cursor']
    assert '''    {
        RepairGfxWords *_g;
        _g = (RepairGfxWords *)arg0;
        arg0 = (void *)((char *)arg0 + 8);
        _g->w0 = 0xE1000000;
        _g->w1 = (unsigned int)(arg3);
        _g = (RepairGfxWords *)arg0;
        arg0 = (void *)((char *)arg0 + 8);
        _g->w0 = 0xDD0007FF;
        _g->w1 = (unsigned int)(arg2);
    }
    g(arg0, arg1);
''' in children['shared_gfx_cursor']
    assert 'temp_a0' not in children['shared_gfx_cursor']
    assert children['returned_gfx_cursor'].count('RepairGfxWords *_g = ') == 2
    assert 'g(arg0, arg1);' in children['returned_gfx_cursor']


def test_a_returned_cursor_gets_the_shared_pointer_too():
    source = SOURCE.replace('void f(', 'void *f(').replace('g(temp_a0 + 8, arg1);', 'return temp_a0 + 8;')
    children = dict(returned_gfx_cursor.variants(source, 'f'))
    assert 'return arg0;' in children['shared_gfx_cursor']


def test_a_cursor_handed_on_short_of_its_end_or_twice_is_left_alone():
    assert returned_gfx_cursor.variants(SOURCE.replace('temp_a0 + 8, arg1', 'temp_a0, arg1'), 'f') == []
    assert returned_gfx_cursor.variants(SOURCE.replace('arg1);\n}', 'arg1);\n    g(temp_a0 + 8, arg1);\n}'), 'f') == []
    assert returned_gfx_cursor.variants(SOURCE.replace('g(temp_a0 + 8, arg1);', 'if (temp_a0 + 8) {}'), 'f') == []
