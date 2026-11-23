"""A base pointer derived from a symbol before a loop, spelled as symbol-relative reads."""
from decomprepair import registry
from decomprepair import symbol_offset_base_inline as p

SOURCE = '''typedef unsigned char u8;
typedef unsigned int u32;
typedef int s32;
extern s32 gMode;
extern u8 gMask;
extern void draw(u32);

void frame(void)
{
    s32 *mode;
    u8 *flags;
    u32 i;
    u32 mask;
    mode = &gMode;
    flags = ((u8 *) mode) - 0x21;
    i = 0;
    do
    {
        mask = 1U << i;
        if (flags[0] & mask)
        {
            draw(i);
        }
        if (flags[-1] & mask)
        {
            draw(mask);
        }
        i += 1;
    }
    while (i < 6);
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'frame')]


def test_the_reads_name_the_symbol_and_the_base_pointer_goes():
    (text,) = texts(SOURCE)
    assert 'flags' not in text
    assert 'if (((u8 *) &gMode)[-33] & mask)' in text
    assert 'if (((u8 *) &gMode)[-34] & mask)' in text
    assert 'mode = &gMode;' in text


def test_a_symbol_address_written_in_the_assignment_is_used_directly():
    text, = texts(SOURCE.replace('flags = ((u8 *) mode) - 0x21;', 'flags = ((u8 *) &gMode) - 0x21;'))
    assert '((u8 *) &gMode)[-33]' in text


def test_a_plus_offset_and_hex_indexes_keep_their_spelling():
    source = SOURCE.replace('- 0x21', '+ 0x10').replace('flags[0]', 'flags[0x2]')
    text, = texts(source)
    assert '((u8 *) &gMode)[0x12]' in text and '((u8 *) &gMode)[15]' in text


def test_the_wider_element_type_scales_the_same_way():
    source = SOURCE.replace('u8 *flags', 'u32 *flags').replace('((u8 *) mode)', '((u32 *) mode)')
    text, = texts(source)
    assert '((u32 *) &gMode)[-33]' in text


def test_a_base_that_is_dereferenced_is_left_alone():
    assert not texts(SOURCE.replace('draw(mask);', 'draw(*flags);'))


def test_a_base_assigned_twice_is_left_alone():
    assert not texts(SOURCE.replace('i = 0;', 'i = 0; flags = flags;'))
    assert not texts(SOURCE.replace('i += 1;', 'i += 1; flags = ((u8 *) mode) - 0x20;'))


def test_a_base_from_a_parameter_pointer_is_left_alone():
    source = SOURCE.replace('void frame(void)', 'void frame(s32 *mode)').replace('    s32 *mode;\n', '').replace(
        '    mode = &gMode;\n', '')
    assert not texts(source)


def test_an_origin_that_is_not_one_assignment_is_left_alone():
    assert not texts(SOURCE.replace('mode = &gMode;', 'mode = &gMode; mode = mode + 1;'))


def test_a_volatile_function_is_left_alone():
    assert not texts(SOURCE.replace('u32 mask;', 'volatile u32 mask;'))


def test_the_module_declares_itself():
    assert 'symbol_offset_base_inline' in {entry.module for entry in registry.declared()}
    repair, = [r for r in registry.declared() if r.module == 'symbol_offset_base_inline']
    assert registry.problems(repair) == []
