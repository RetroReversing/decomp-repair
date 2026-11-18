"""Byte offsets m2c added to symbols of unknown type: in elements of the draft's M2C_UNK, or as bytes."""
from decomprepair import unknown_symbol_offset_repairs as u

SOURCE = '''extern M2C_UNK D_800C0784;
extern M2C_UNK D_800C0788;

void f(void *arg0, s32 arg2) {
    s32 temp_a2;

    temp_a2 = arg2 * 0x10;
    if (*(&D_800C0784 + temp_a2) != 0) {
        *(s32 *)arg0 = *(&D_800C0788 + temp_a2);
    }
}
'''


def texts(source=SOURCE, name='f'):
    return [out for family, out in u.variants(source, name)]


def test_temporary_offset_in_elements_bytes_and_folded():
    # An N64 game: a table of 16-byte records, `arg2 * 0x10` scaled by 4 again gave `sll 6` for the game's `sll 4`.
    element, byte, folded = texts()
    assert all(f == 'unknown_symbol_offsets' for f, _ in u.variants(SOURCE, 'f'))
    assert 'temp_a2 = arg2 * 0x4;' in element and '*(&D_800C0784 + temp_a2)' in element
    assert '*((M2C_UNK *)((s8 *)&D_800C0784 + temp_a2))' in byte and 'temp_a2 = arg2 * 0x10;' in byte
    assert '*((M2C_UNK *)((s8 *)&D_800C0788 + (arg2 * 0x10)))' in folded and 'temp_a2 =' not in folded


def test_inline_offsets_and_sizes():
    source = '''extern M2C_UNK16 D_1;
extern M2C_UNK D_2;
s32 g(s32 i) { return *(&D_1 + (i * 6)) + *(&D_2 + 8) + *(&D_2 + (i << 3)); }
'''
    element = texts(source, 'g')[0]
    assert '*(&D_1 + i * 3)' in element and '*(&D_2 + 2)' in element and '*(&D_2 + i << 1)' in element
    assert '((M2C_UNK16 *)((s8 *)&D_1 + (i * 6)))' in texts(source, 'g')[1]


def test_left_alone_or_bytes_only():
    # not a multiple of the size: the byte form only
    odd = SOURCE.replace('arg2 * 0x10', 'arg2 * 6')
    outs = texts(odd)
    assert outs and not any('arg2 * 0x' in o or 'arg2 * 1;' in o for o in outs)
    # the temporary is used for something else too: its value stays, so no element form
    other = SOURCE.replace('*(s32 *)arg0 = *(&D_800C0788 + temp_a2);', '*(s32 *)arg0 = temp_a2;')
    assert not any('arg2 * 0x4' in o for o in texts(other))
    # a symbol whose type the source knows, or one the header declares: nothing
    assert not texts(SOURCE.replace('extern M2C_UNK D_800C0784;', 'extern s32 D_800C0784;')
                     .replace('extern M2C_UNK D_800C0788;', 'extern s32 D_800C0788;'))
    # a value whose operands change before its uses can't be folded
    moved = SOURCE.replace('    if (', '    arg2 = 0;\n    if (')
    assert len(texts(moved)) == 2


def test_propose_finds_the_family():
    from decomprepair.propose import propose
    assert any(p.module == 'unknown_symbol_offset_repairs' and 'arg2 * 0x4' in p.source
               for p in propose(SOURCE, 'f').proposals)
