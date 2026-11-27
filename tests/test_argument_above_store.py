from decomprepair import argument_above_store as repair

HEAD = '''typedef struct { s32 id; char text[0x40]; } Line;
extern s32 gLine;
extern u8 gColumn;
extern Line sLines[];
extern Rec gColor;
void draw(char *, s32, s32, Rec *);
'''

DIRECT = HEAD + '''
void show(void) {
    Rec color = gColor;

    sLines[gLine].text[gColumn + 1] = 0;
    draw(sLines[gLine].text, 0x5F, gLine * 15 + 0x3C, &color);
}
'''

COPIED = HEAD + '''
void show(void) {
    Rec color = gColor;
    s32 line = gLine;

    sLines[line].text[gColumn + 1] = 0;
    draw(sLines[gLine].text, 0x5F, line * 15 + 0x3C, &color);
}
'''


def children(source, family):
    return [child for label, child in repair.variants(source, 'show') if label == family]


def test_assigns_the_argument_above_the_store():
    [child] = children(DIRECT, repair.HOIST)
    assert '    s32 held;\n' in child
    assert '    held = gLine * 15 + 0x3C;\n    sLines[gLine]' in child
    assert 'draw(sLines[gLine].text, 0x5F, held, &color);' in child


def test_the_copy_holds_the_whole_argument():
    [child] = children(COPIED, repair.DERIVE)
    assert 's32 line = gLine * 15 + 0x3C;' in child
    assert 'sLines[gLine].text[gColumn + 1] = 0;' in child
    assert 'draw(sLines[gLine].text, 0x5F, line, &color);' in child


def test_a_store_to_the_global_read_or_through_a_pointer_stops_it():
    for store in ('gLine = 0;', '*p = 0;'):
        assert repair.variants(DIRECT.replace('sLines[gLine].text[gColumn + 1] = 0;', store), 'show') == []
        assert repair.variants(COPIED.replace('sLines[line].text[gColumn + 1] = 0;', store), 'show') == []


def test_a_call_between_stops_it():
    assert children(COPIED.replace('= 0;\n    draw', '= 0;\n    tick();\n    draw'), repair.DERIVE) == []
    assert children(DIRECT.replace('= 0;\n    draw', '= 0;\n    tick();\n    draw'), repair.HOIST) == []


def test_a_local_read_after_the_call_is_left_alone():
    assert children(COPIED.replace('&color);\n}', '&color);\n    gColumn = line;\n}'), repair.DERIVE) == []
