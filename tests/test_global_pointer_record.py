"""A global pointer reloaded before each store through it, as a one-member record (a 2,503-instruction update, 5435 -> 4835)."""
from decomprepair.global_pointer_record import FAMILY, variants

SOURCE = """extern void *gBlock;
extern void *gOther;

void update(void *arg0)
{
    (*(f32 *)((char *)(gBlock) + 0x34)) = (*(f32 *)((char *)(arg0) + 0x3C)) * 0.5f;
    (*(f32 *)((char *)(gBlock) + 0x38)) = (*(f32 *)((char *)(arg0) + 0x40)) * 0.5f;
    use(gOther);
    (*(f32 *)((char *)(gOther) + 4)) = 1.0f;
}
"""


def test_the_stored_through_global_becomes_a_record_member():
    found = variants(SOURCE, 'update', '')
    assert [family for family, _ in found] == [FAMILY]
    text = found[0][1]
    assert text.startswith('extern struct { void *block; } gBlock;\nextern void *gOther;\n')
    assert '(*(f32 *)((char *)(gBlock.block) + 0x34)) =' in text and '(gBlock.block) + 0x38' in text
    assert 'use(gOther);' in text


def test_a_global_the_header_declares_or_whose_address_is_taken_is_left_alone():
    assert variants(SOURCE, 'update', 'extern void *gBlock;\n') == []
    assert variants(SOURCE.replace('    use(gOther);', '    use(&gBlock);'), 'update', '') == []


def test_an_assigned_pointer_stored_through_m2c_fields_is_a_record():
    source = '''extern void *gVoice;

void setup(void)
{
    void *temp;

    temp = alloc();
    gVoice = temp;
    M2C_FIELD(temp, s32 *, 0x80) = 1;
    M2C_FIELD(gVoice, s16 *, 0x6A) = 0;
    M2C_FIELD(gVoice, s8 *, 0x7A) = 5;
}
'''
    found = variants(source, 'setup', '')
    assert [family for family, _ in found] == [FAMILY]
    assert found[0][1] == source.replace('extern void *gVoice;', 'extern struct { void *block; } gVoice;').replace(
        'gVoice = temp;', 'gVoice.block = temp;').replace('(gVoice,', '(gVoice.block,')


def test_a_scalar_global_updated_in_place_becomes_a_record_member():
    source = 'extern s32 gCount;\nextern s32 gRead;\n\nvoid bump(void)\n{\n    if (gRead) {\n        gCount += 1;\n    }\n}\n'
    found = variants(source, 'bump', '')
    assert [family for family, _ in found] == ['global_scalar_record']
    assert found[0][1] == source.replace('extern s32 gCount;', 'extern struct { s32 value; } gCount;').replace(
        'gCount += 1;', 'gCount.value += 1;')
    assert variants(source, 'bump', 'extern s32 gCount;') == []


READ = """extern void *gParam;

void update(void *obj)
{
    if (M2C_FIELD(gParam, u16 *, 0x6A) != 0xFFFF) {
        M2C_FIELD(obj, u16 *, 2) = M2C_FIELD(gParam, u16 *, 2);
        if (M2C_FIELD(gParam, s32 *, 0x80) != 0xC8) {
            done(obj);
        }
    }
}
"""


def test_a_global_pointer_read_again_after_a_store_becomes_a_record_member():
    found = variants(READ, 'update', '')
    assert [family for family, _ in found] == ['global_pointer_read_record']
    assert found[0][1] == READ.replace('extern void *gParam;', 'extern struct { void *block; } gParam;').replace(
        '(gParam,', '(gParam.block,')
    assert variants(READ, 'update', 'extern void *gParam;') == []


def test_reads_with_no_store_between_are_left_alone():
    assert variants(READ.replace('M2C_FIELD(obj, u16 *, 2) = M2C_FIELD(gParam, u16 *, 2);', 'g(gParam);'), 'update', '') == []


def test_an_address_local_is_written_out_before_the_record():
    source = '''extern void *gParam;

void update(void)
{
    void **base;
    base = &gParam;
    (*(s32 *)((char *)((*base)) + 0x20)) = 0;
    (*(s32 *)((char *)((*base)) + 0x24)) = 0;
}
'''
    found = variants(source, 'update', '')
    assert [family for family, _ in found] == ['global_pointer_base_record']
    text = found[0][1]
    assert text.startswith('extern struct { void *block; } gParam;\n') and 'base' not in text
    assert '(*(s32 *)((char *)(gParam.block) + 0x24)) = 0;' in text
    assert variants(source.replace('    (*(s32 *)((char *)((*base)) + 0x20)) = 0;', '    use(base);'), 'update', '') == []
