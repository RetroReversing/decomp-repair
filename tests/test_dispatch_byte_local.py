from decomprepair.dispatch_byte_local import FAMILY, variants

GOTO_FORM = '''
void f(u8 *code, s32 *out)
{
    s32 n = 0;
    goto test;
    again:
    switch (code[0]) {
    case 1:
        code += 2;
        goto test;
    case 2:
        out[n++] = code[1];
        code += 2;
        goto test;
    default:
        goto test;
    }
    test:
    if (code[0] != 12) {
        {
            long long wide = n;
        }
        goto again;
    }
}
'''

WHILE_FORM = '''
void g(u8 *code, s32 *out)
{
    s32 n = 0;
    while (*code != 12) {
        switch (*code) {
        case 1:
            code += 2;
            break;
        default:
            out[n++] = code[1];
            code += 2;
            break;
        }
    }
}
'''


def local(source, name):
    return [text for family, text in variants(source, name) if family == FAMILY]


def test_the_opcode_is_read_once_in_the_gotos_loop_test():
    text, = local(GOTO_FORM, 'f')
    assert 'u8 op;' in text and 'switch (op)' in text
    assert '    test:\n    op = code[0];\n    if (op != 12) {' in text


def test_the_opcode_is_read_once_in_the_while_form():
    text, = local(WHILE_FORM, 'g')
    assert 'while ((op = *code) != 12) {\n        switch (op) {' in text
    assert text.count('u8 op;') == 1


def test_a_store_between_the_test_and_the_switch_stays():
    assert not local(GOTO_FORM.replace('long long wide = n;', 'out[0] = 1;'), 'f')
    assert not local(GOTO_FORM.replace('long long wide = n;', 'code += 1;'), 'f')


def test_a_switch_on_another_byte_stays():
    assert not local(WHILE_FORM.replace('switch (*code)', 'switch (code[1])'), 'g')


def test_a_name_already_taken_gets_another():
    text, = local(WHILE_FORM.replace('s32 n = 0;', 's32 n = 0; s32 op = 0;'), 'g')
    assert 'u8 op_;' in text and 'switch (op_)' in text


def test_a_word_pointer_stays():
    assert not local(WHILE_FORM.replace('u8 *code', 'u32 *code'), 'g')
