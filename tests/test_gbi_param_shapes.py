from decomprepair.gbi_macro_commands import PARAMETER_FAMILY
from decomprepair.gbi_macro_commands import variants as macro_variants
from decomprepair.gbi_param_shapes import FAMILY, variants


def draft(commands, params, values=''):
    """An m2c draft that writes `commands` through a cursor the caller passes by address."""
    count = len(commands)
    names = ''.join(f'    void *temp_a{k};\n' for k in range(count))
    body = ['    temp_a0 = *arg0;']
    for k, (first, second) in enumerate(commands):
        if k + 1 < count:
            body.append(f'    temp_a{k + 1} = temp_a{k} + 8;')
        body.append(f'    M2C_FIELD(temp_a{k}, s32 *, 0) = {first};')
        body.append(f'    M2C_FIELD(temp_a{k}, s32 *, 4) = {second};')
    body.append(f'    *arg0 = temp_a{count - 1} + 8;')
    declared = ''.join(f'    s32 {n};\n' for n in ('temp_t0', 'temp_t1') if n in values)
    return (f'void draw({params}) {{\n{declared}{names}\n{values}' + '\n'.join(body) + '\n}\n')


PARAMS = 'void **arg0, s32 arg1, s32 arg3, s32 arg4, s32 arg5'
VALUES = '    temp_t0 = arg1 & 0xFFFF;\n    temp_t1 = ((s16) arg5 + (s16) arg3) - 1;\n'
LINE = '((((s32) ((s16) arg3 + 7) >> 3) & 0x1FF) << 9) | 0xF5480000'
COMMANDS = [
    (LINE, '((arg4 & 3) << 0x12) | 0x07000000 | ((arg4 & 0xF) * 0x10)'),
    ('((((s16) arg5 * 4) & 0xFFF) << 0xC) | 0xF4000000', '(((temp_t1 * 4) & 0xFFF) << 0xC) | 0x07000000'),
    ('(((temp_t0 * 4) & 0xFFF) << 0xC) | 0xE4000000', '0'),
    ('0xB4000000', 'arg5 << 0x15'),
    ('0xB3000000', '0x04000400'),
]


def child(source):
    found = variants(source, 'draw')
    assert found and found[0][0] == FAMILY
    return found[0][1]


def test_the_finished_source_has_the_missing_parameter_and_the_widths():
    text = child(draft(COMMANDS, PARAMS, VALUES))
    assert 'void draw(void **arg0, u16 arg1, s32 arg2, s16 arg3, s32 arg4, s16 arg5)' in text
    assert 'temp_t0' not in text and 'temp_t1' not in text


def test_a_multiplied_mask_and_a_shift_past_the_top_field_decode():
    text = child(draft(COMMANDS, PARAMS, VALUES))
    assert 'gSPTextureRectangleF3D(gfx++, ' in text and 'arg5 << 5' in text
    assert 'gRawWords' not in text.split('void draw')[1]
    assert 'gDPSetTile(gfx++, 2, 1, ' in text


def test_the_tile_line_is_written_from_the_loaded_edges():
    text = child(draft(COMMANDS, PARAMS, VALUES))
    assert '(((((arg5 + arg3) - 1) - arg5) + 1) + 7) >> 3' in text


def test_the_cursor_is_read_before_the_values():
    values = VALUES + '    arg4 = arg4 & 3;\n'
    text = child(draft(COMMANDS, PARAMS, values))
    assert text.index('{ Gfx *gfx') < text.index('arg4 = arg4 & 3;')


def test_a_wrapper_that_splits_the_run_is_opened():
    source = draft(COMMANDS, PARAMS, VALUES)
    start = source.index('    temp_a0 = *arg0;')
    middle = source.index('    temp_a2 = temp_a1 + 8;')
    fenced = source[:start] + '    do {\n' + source[start:middle] + '    } while (0);\n' + source[middle:]
    assert not [t for f, t in macro_variants(fenced, 'draw') if f == PARAMETER_FAMILY]
    assert 'gSPTextureRectangleF3D(gfx++, ' in child(fenced)


def test_a_function_without_a_cursor_argument_is_left_alone():
    assert variants('void draw(s32 arg0) {\n    D_0 = arg0;\n}\n', 'draw') == []
