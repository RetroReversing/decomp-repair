"""string_walk_index: a byte string walked by a pointer written as the index loop it came from.

Shape of an 82-instruction KMC text-measuring routine (saved best 360: the walked pointer's start was emitted after the
jump table's address, the target has `la, move, addu`; the indexed source scored 0 with no other edit)."""
from decomprepair import string_walk_index as w

SOURCE = '''s32 callee(u8 *font, char *at);

s32 measure(char *text, u16 size, u8 *font)
{
    s32 width = 0;
    u16 length = size;
    char *cursor;
    u8 symbol;

    if (length != 0) {
        cursor = text;
        do {
            symbol = *cursor;
            switch (symbol) {
            case 6:
                cursor++;
                break;
            case 3:
                cursor++;
                width = (s8)*cursor * 2;
                break;
            default:
                width += callee(font, cursor) + cursor[1];
                break;
            }
            cursor++;
        } while (cursor < (char *)((u32)length + (u32)text));
    }
    return width;
}
'''


def test_the_pointer_walk_becomes_the_index_loop():
    found = [text for family, text in w.variants(SOURCE, 'measure') if family == w.FAMILY]
    assert len(found) == 1
    text = found[0]
    assert 'char *cursor' not in text and 'u32 i;' in text
    assert 'i = 0;' in text and 'symbol = text[i];' in text
    assert 'width = (s8)text[i] * 2;' in text
    assert 'callee(font, (text + i)) + text[i + 1]' in text
    assert text.count('i++;') == 3
    assert '} while (i < length);' in text
    assert 'cursor' not in text.split('{', 1)[1]


def test_a_for_loop_over_the_pointer_is_converted():
    source = '''s32 sum(u8 *data, u32 n)
{
    u8 *p;
    s32 total = 0;
    for (p = data; p < data + n; p++) {
        total += *p;
    }
    return total;
}
'''
    found = [text for _, text in w.variants(source, 'sum')]
    assert found and 'for (i = 0; i < n; i++)' in found[0] and 'total += data[i];' in found[0]


def test_nothing_is_offered_when_the_pointer_escapes_the_loop():
    used_after = SOURCE.replace('    return width;', '    return width + (s32)cursor;')
    assert w.variants(used_after, 'measure') == []
    stepped_in_expression = SOURCE.replace('symbol = *cursor;', 'symbol = *cursor++;')
    assert w.variants(stepped_in_expression, 'measure') == []
    address_taken = SOURCE.replace('callee(font, cursor)', 'callee(font, (char *)&cursor)')
    assert w.variants(address_taken, 'measure') == []


def test_nothing_is_offered_when_the_test_is_not_base_plus_length():
    other = SOURCE.replace('(char *)((u32)length + (u32)text)', 'stop')
    assert w.variants(other, 'measure') == []
    moved_base = SOURCE.replace('            cursor++;\n                break;\n            case 3:', '            text++;\n                break;\n            case 3:')
    assert w.variants(moved_base, 'measure') == []


def test_a_counter_name_already_in_use_is_not_taken():
    taken = SOURCE.replace('s32 width = 0;', 's32 width = 0;\n    s32 i = 0;')
    found = [text for _, text in w.variants(taken, 'measure')]
    assert found and 'u32 index;' in found[0] and 'symbol = text[index];' in found[0]
