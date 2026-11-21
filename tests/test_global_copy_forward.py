"""A local copy of a stored global is read back from the global."""
from decomprepair import global_copy_forward as g

DRAFT = '''extern u16 gStamp;
extern u32 gCount;
extern u16 *gTable[];

void f(void) {
    u32 i;
    u32 count;
    s32 stamp;
    u32 s0 = gStamp + 1;
    count = gCount;
    gStamp = s0;
    stamp = s0;
    for (i = 0; i < gCount; i++) {
        if (gTable[i][0] != (u16)stamp) {
            gTable[i][0] = stamp;
        }
    }
}
'''


def test_the_copy_is_read_from_the_global_and_goes():
    (family, text), = g.variants(DRAFT, 'f')
    assert family == 'global_copy_forward'
    assert 'stamp' not in text
    assert 'gTable[i][0] != (u16)gStamp' in text and 'gTable[i][0] = gStamp;' in text
    assert 'u32 s0 = gStamp + 1;' in text and '    gStamp = s0;' in text
    assert 's32 stamp;' not in text


def test_a_call_after_the_store_or_another_write_to_the_global_leaves_it_alone():
    assert g.variants(DRAFT.replace('gTable[i][0] = stamp;', 'gTable[i][0] = stamp; h();'), 'f') == []
    assert g.variants(DRAFT.replace('gTable[i][0] = stamp;', 'gStamp = 3;'), 'f') == []
    assert g.variants(DRAFT.replace('gTable[i][0] = stamp;', 'stamp = 3;'), 'f') == []
    assert g.variants(DRAFT.replace('    gStamp = s0;\n', ''), 'f') == []


def test_a_use_before_the_copy_is_not_forwarded():
    early = DRAFT.replace('    stamp = s0;\n', '    gTable[0][0] = stamp;\n    stamp = s0;\n')
    assert g.variants(early, 'f') == []


def test_a_field_with_the_copy_name_is_not_renamed():
    field = DRAFT.replace('gTable[i][0]', 'gTable[i]->stamp')
    (family, text), = g.variants(field, 'f')
    assert 'gTable[i]->stamp != (u16)gStamp' in text and 'gTable[i]->stamp = gStamp;' in text
