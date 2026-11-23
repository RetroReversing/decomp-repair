"""call_result_join_copy: a call's pointer result copied after the first join, the stray carrier argument dropped.

Synthetic shape of a 118-instruction KMC menu function (470 -> 60 with the copy and the dropped argument together, 80
with the copy alone): m2c names the one pointer a call returns `item`, stores it to a global, and passes it on as the
third argument of a callee every other caller gives two."""
from decomprepair import call_result_join_copy as s

SOURCE = '''typedef struct { u8 pad[16]; u32 color; } Item;
Item *make(s32, s32);
void show(void *, s32, Item *);
extern Item *gCurrent;
extern u16 gPhase;
extern u32 gTable[];
extern u8 gShow;

void draw(void *list, s32 mode) {
    Item *item;
    u32 phase;
    u32 *color;
    item = make(mode, 0);
    gCurrent = item;
    phase = gPhase & 63;
    if (phase >= 32) {
        phase = 63 - phase;
    }
    if (mode & 1) {
        color = gTable + 1;
    } else {
        color = gTable + 9;
    }
    item->color = *color & ~255;
    if (gShow) {
        show(list, 1, item);
    }
}
'''


def _found(source=SOURCE):
    result = {}
    for family, text in s.variants(source, 'draw'):
        result.setdefault(family, []).append(text)
    return result


def test_the_copy_follows_the_first_join_and_takes_every_later_use():
    text = _found()[s.FAMILY][0]
    assert 'Item *item_copy;' in text
    assert '    }\n    item_copy = item;\n    if (mode & 1) {' in text
    assert 'item_copy->color = *color & ~255;' in text and 'show(list, 1, item_copy);' in text
    assert 'gCurrent = item;' in text  # the original is still read before the copy


def test_the_copy_alone_renames_only_member_accesses():
    text = _found()[s.DEREF_FAMILY][0]
    assert 'item_copy->color' in text and 'show(list, 1, item);' in text


def test_the_stray_trailing_argument_and_the_last_parameter_go_with_the_copy():
    text = _found()[s.DROP_FAMILY][0]
    assert 'void show(void *, s32);' in text and 'show(list, 1);' in text
    assert 'item_copy->color' in text and 'item_copy = item;' in text


def test_a_second_join_is_offered_too():
    texts = _found()[s.FAMILY]
    assert len(texts) == 2 and 'item_copy = item;\n    item_copy->color' in texts[1]


def test_a_copy_needs_a_use_of_the_original_before_it():
    assert s.variants(SOURCE.replace('    gCurrent = item;\n', ''), 'draw') == []


def test_a_copy_needs_a_use_after_the_join():
    early = SOURCE.replace('    item->color = *color & ~255;\n    if (gShow) {\n        show(list, 1, item);\n    }\n', '')
    assert s.variants(early, 'draw') == []


def test_a_loop_a_second_set_or_a_parameter_declines():
    assert s.variants(SOURCE.replace('    if (gShow) {', '    while (gShow--) {'), 'draw') == []
    assert s.variants(SOURCE.replace('item = make(mode, 0);', 'item = make(mode, 0);\n    item = make(mode, 1);'), 'draw') == []
    param = SOURCE.replace('    Item *item;\n', '').replace('void draw(void *list, s32 mode)', 'void draw(Item *item, s32 mode)')
    assert s.variants(param, 'draw') == []


def test_a_read_after_the_assigning_block_declines():
    nested = SOURCE.replace('    item = make(mode, 0);\n', '    if (mode) {\n    item = make(mode, 0);\n').replace(
        '        show(list, 1, item);\n    }\n}', '        show(list, 1, item);\n    }\n    }\n    gCurrent = item;\n}')
    assert s.variants(nested, 'draw') == []


def test_an_untyped_prototype_drops_only_the_call_argument():
    text = dict(s.variants(SOURCE.replace('void show(void *, s32, Item *);', 'void show();'), 'draw'))[s.DROP_FAMILY]
    assert 'void show();' in text and 'show(list, 1);' in text


def test_the_module_declares_itself_for_the_registry():
    assert s.REPAIR['variants'] is s.variants and s.REPAIR['families'] == s.FAMILIES
