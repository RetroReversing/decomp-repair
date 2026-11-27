from decomprepair import array_cursor_counter as family

HEADER = '''typedef struct { short x; short y; short z; short w; } Out;
typedef struct { short x; short y; unsigned char r; unsigned char g; int kind; } Item;
extern Item *gItem;
extern Item gPool[];
extern Out gOut[];
extern unsigned char gColour[];
'''

SOURCE = HEADER + '''void emit(void)
{
    unsigned short i;
    Out *pos;
    unsigned char *colour;

    gItem = gPool;
    pos = gOut;
    colour = gColour;
    for (i = 0; i != 500; i++) {
        if (gItem->kind != 0) {
            pos->x = gItem->x;
            pos->y = gItem->y;
            pos->z = 0;
            *colour++ = gItem->r;
            *colour++ = gItem->g;
            pos++;
        }
        gItem++;
    }
}
'''


def test_all_cursors_together_come_first():
    children = family.variants(SOURCE, 'emit')
    assert [name for name, _ in children] == ['array_cursor_counter'] * 3
    together = children[0][1]
    assert 'int pos_index;' in together and 'int colour_index;' in together
    assert 'pos_index = 0;' in together and 'colour_index = 0;' in together
    assert 'gOut[pos_index].x = gItem->x;' in together
    assert 'gColour[colour_index++] = gItem->r;' in together
    assert 'pos_index++;' in together
    assert 'gItem++;' in together
    assert 'pos->' not in together and 'colour++' not in together


def test_initialiser_steps_and_indexed_uses():
    source = HEADER + '''void emit(int n)
{
    Out *pos = &gOut[0];

    while (n--) {
        pos[0].x = 1;
        pos[1].x = 2;
        (*pos).y = 3;
        use(pos);
        pos += 2;
    }
}
'''
    child = family.variants(source, 'emit')[0][1]
    assert 'int pos_index = 0;' in child
    assert 'gOut[pos_index].x = 1;' in child
    assert 'gOut[pos_index + (1)].x = 2;' in child
    assert '(gOut[pos_index]).y = 3;' in child
    assert 'use((gOut + pos_index));' in child
    assert 'pos_index += 2;' in child


def test_refused_when_the_pointer_is_not_the_array_at_a_counter():
    other_type = SOURCE.replace('extern Out gOut[];', 'extern int gOut[];')
    assert all('pos_index' not in child for _, child in family.variants(other_type, 'emit'))
    from_elsewhere = SOURCE.replace('pos = gOut;', 'pos = gItem->kind ? gOut : 0;')
    assert all('pos_index' not in child for _, child in family.variants(from_elsewhere, 'emit'))
    address_taken = SOURCE.replace('pos++;', 'pos++;\n            use(&pos);')
    assert all('pos_index' not in child for _, child in family.variants(address_taken, 'emit'))
    read_first = SOURCE.replace('gItem = gPool;', 'gItem = gPool;\n    use(pos);')
    assert all('pos_index' not in child for _, child in family.variants(read_first, 'emit'))
    never_stepped = SOURCE.replace('pos++;', '')
    assert all('pos_index' not in child for _, child in family.variants(never_stepped, 'emit'))
