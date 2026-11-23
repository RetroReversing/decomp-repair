"""stray_global_call_argument: a global m2c passed as a trailing argument, dropped from the calls and the prototype.

Synthetic shape of a 525-instruction KMC display-list builder (55 -> 0): m2c passed the display-list cursor the argument
register still held to a one-argument helper, with a prototype written to fit."""
from decomprepair import stray_global_call_argument as s

SOURCE = '''typedef struct { u32 w0; u32 w1; } Gfx;
s32 helper(s32, void *);
s32 load(f32 *, s32);
s32 mix(f32 *, f32 *, f32 *);
extern Gfx *sCursor;
extern s32 sSlot;
extern f32 sMatrix[];

void draw(s32 id) {
    sSlot = id << 6;
    load(sMatrix, sSlot);
    mix(sMatrix, sMatrix, sMatrix);
    sCursor->w0 = 0xDA380003;
    sCursor++;
    helper(id, sCursor);
    helper(id + 1, sCursor);
}
'''


def _children():
    return [text for family, text in s.variants(SOURCE, 'draw') if family == s.FAMILY]


def test_the_cursor_argument_goes_from_every_call_and_the_prototype():
    texts = _children()
    helper = [t for t in texts if 'helper(id);' in t and 'load(sMatrix, sSlot);' in t]
    assert len(helper) == 1
    text = helper[0]
    assert 's32 helper(s32);' in text and 'helper(id + 1);' in text
    assert 's32 load(f32 *, s32);' in text


def test_each_callee_alone_and_all_together():
    texts = _children()
    assert len(texts) == 3
    assert any('load(sMatrix);' in t and 'helper(id);' in t and 's32 load(f32 *);' in t for t in texts)


def test_arrays_twice_passed_values_locals_and_header_callees_are_left_alone():
    texts = _children()
    assert all('mix(sMatrix, sMatrix, sMatrix);' in t for t in texts)
    shadowed = SOURCE.replace('void draw(s32 id) {\n', 'void draw(s32 id) {\n    Gfx *sCursor;\n    s32 sSlot;\n')
    assert s.variants(shadowed, 'draw') == []
    assert all('helper(id);' not in t for _, t in s.variants(SOURCE, 'draw', header='s32 helper(s32, void *);\n'))


def test_a_one_argument_call_keeps_a_void_prototype():
    one = SOURCE.replace('s32 helper(s32, void *);', 's32 helper(void *);').replace('helper(id, sCursor);', 'helper(sCursor);')
    one = one.replace('    helper(id + 1, sCursor);\n', '')
    text = [t for t in (t for _, t in s.variants(one, 'draw')) if 'helper();' in t][0]
    assert 's32 helper(void);' in text


def test_the_module_declares_itself():
    assert s.REPAIR['families'] == (s.FAMILY,) and 'header' in s.REPAIR['needs']
