from decomprepair.paired_call_argument_inline_repairs import FAMILY, variants

SOURCE = '''void f(s32 k, u8 *rec, void *ctx)
{
    s32 v;
    switch (k)
    {
        case 1:
            v = M2C_FIELD(rec, u8 *, 0x1E) + 0x6F;
            send(ctx, v & 0xFF);
            break;
        case 2:
            v = M2C_FIELD(rec, u8 *, 0x1E) + 0x6D;
            send(ctx, v & 0xFF);
            break;
    }
}
'''


def moved(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_each_assignment_and_all_of_them_go_into_their_calls():
    texts = moved()
    assert len(texts) == 3
    both = texts[-1]
    assert 'send(ctx, (M2C_FIELD(rec, u8 *, 0x1E) + 0x6F) & 0xFF);' in both
    assert 'send(ctx, (M2C_FIELD(rec, u8 *, 0x1E) + 0x6D) & 0xFF);' in both
    assert 'v = ' not in both
    one = texts[0]
    assert 'send(ctx, (M2C_FIELD(rec, u8 *, 0x1E) + 0x6F) & 0xFF);' in one and 'v = M2C_FIELD(rec, u8 *, 0x1E) + 0x6D;' in one


def test_a_local_read_anywhere_else_stays():
    other = SOURCE.replace('    }\n}', '    }\n    after(v);\n}')
    assert not moved(other)


def test_a_call_in_the_expression_or_another_argument_is_never_moved():
    assert not moved(SOURCE.replace('M2C_FIELD(rec, u8 *, 0x1E) + 0x6F', 'next() + 0x6F'))
    assert not moved(SOURCE.replace('send(ctx, v & 0xFF);\n            break;\n        case 2', 'send(next(), v & 0xFF);\n            break;\n        case 2'))
