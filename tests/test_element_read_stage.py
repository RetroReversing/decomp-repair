"""element_read_stage: a table element read after a run of stores, its address hoisted ahead of the fence and its value
read after the first store, one child.

Synthetic shape of a 136-instruction KMC menu function (60 -> 0 together; 370 with only the address hoisted)."""
from decomprepair import element_read_stage as s

SOURCE = '''extern s32 sTable[];
extern u8 gA;
extern u8 gB;
extern u8 gOut;
void pick(u8 arg0)
{
    long slot;
    slot = arg0;
    do { gA = 0; gB = 1; if (sTable[slot] != 0) { gOut = arg0; } else { gOut = 0; } } while (0);
}
'''


def test_the_address_and_the_staged_read_are_one_child():
    found = dict.fromkeys(text for _, text in s.variants(SOURCE, 'pick'))
    staged = [t for t in found if 'elem_v = *elem_p;' in t]
    assert staged
    text = next(t for t in staged if 'gA = 0; elem_v = *elem_p; gB = 1;' in t)
    assert '{ s32 *elem_p = &sTable[slot]; s32 elem_v; do {' in text
    assert 'if (elem_v != 0)' in text and text.rstrip().endswith('}')
    assert '} while (0); }' in text


def test_the_address_alone_and_the_read_before_the_if_are_offered():
    texts = [text for _, text in s.variants(SOURCE, 'pick')]
    assert any('if (*elem_p != 0)' in t and 'elem_v' not in t for t in texts)
    assert any('gB = 1; elem_v = *elem_p; if (elem_v != 0)' in t for t in texts)


def test_a_block_without_a_fence_gets_the_scope_at_its_head():
    plain = SOURCE.replace('do { gA = 0;', '{ gA = 0;').replace('} while (0);', '}')
    texts = [text for _, text in s.variants(plain, 'pick')]
    assert texts and all('{ s32 *elem_p = &sTable[slot];' in t for t in texts)


def test_a_store_that_could_change_the_element_or_index_declines():
    aliasing = SOURCE.replace('gB = 1;', 'slot = 2;')
    assert s.variants(aliasing, 'pick') == []
    volatile = SOURCE.replace('extern s32 sTable[];', 'extern volatile s32 sTable[];')
    assert s.variants(volatile, 'pick') == []
    unknown = SOURCE.replace('extern s32 sTable[];', '')
    assert s.variants(unknown, 'pick') == []
    called = SOURCE.replace('gB = 1;', 'g();')
    assert s.variants(called, 'pick') == []
