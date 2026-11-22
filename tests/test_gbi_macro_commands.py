import os
import re
import shutil
import subprocess

import pytest

from decomprepair import gbi_macro_commands as g

# m2c's shape of a texture load: one read of the cursor, the words in the scheduler's order, a value computed between
# them, a later read that continues the run and every advance in a row (a homemade function, not a game's)
DRAFT = '''extern s32 *sCursor;
extern s32 gTex;
void f(s32 w, s32 h)
{
    s32 *temp_v1;
    s32 *temp_v0;
    s32 *temp_a0;
    s32 lrs;
    temp_v1 = sCursor;
    *((s32 *) (((char *) temp_v1) + 0)) = 0xFD900000;
    *((s32 *) (((char *) temp_v1) + 8)) = 0xF5900000;
    *((s32 *) (((char *) temp_v1) + 4)) = gTex;
    *((s32 *) (((char *) temp_v1) + 0xC)) = 0x070C0300;
    *((s32 *) (((char *) temp_v1) + 0x10)) = 0xE6000000;
    *((s32 *) (((char *) temp_v1) + 0x14)) = 0;
    sCursor = temp_v1 + 8;
    sCursor = temp_v1 + 0x10;
    temp_v0 = temp_v1 + 0x10;
    sCursor = temp_v1 + 0x18;
    lrs = (w * h) & 0x7FF;
    temp_a0 = sCursor;
    *((s32 *) (((char *) temp_a0) + 0)) = 0xE7000000;
    *((s32 *) (((char *) temp_a0) + 4)) = 0;
    *((s32 *) (((char *) temp_a0) + 8)) = 0xF2000000;
    *((s32 *) (((char *) temp_a0) + 0xC)) = (((w * 4) & 0xFFF) << 0xC) | ((h * 4) & 0xFFF);
    *((s32 *) (((char *) temp_a0) + 0x10)) = 0xFA000000;
    *((s32 *) (((char *) temp_a0) + 0x14)) = (((gTex >> 0x18) << 0x18) | (gTex & 0xFF0000) | (gTex & 0xFF00) | (gTex & 0xFF));
    *((s32 *) (((char *) temp_a0) + 0x18)) = 0xE3001001;
    *((s32 *) (((char *) temp_a0) + 0x1C)) = lrs << 3;
    sCursor = temp_a0 + 8;
    sCursor = temp_a0 + 0x10;
    sCursor = temp_a0 + 0x18;
    sCursor = temp_a0 + 0x20;
}
'''

# a texture rectangle per arm, m2c's first word hoisted past the join (as in an N64 text renderer's glyph loop)
RECTANGLE = '''extern s32 *sCursor;
void r(s32 x, s32 y, s32 hires, u8 *glyph)
{
    s32 *var_a2;
    s32 var_a1;
    s32 t3;
    t3 = glyph[0] << 5;
    if (hires != 0) {
        var_a2 = sCursor;
        sCursor = var_a2 + 8;
        sCursor = var_a2 + 0x10;
        *((s32 *) (((char *) var_a2) + 8)) = 0xE1000000;
        *((s32 *) (((char *) var_a2) + 0xC)) = t3 << 0x10;
        sCursor = var_a2 + 0x18;
        *((s32 *) (((char *) var_a2) + 0x10)) = 0xF1000000;
        *((s32 *) (((char *) var_a2) + 4)) = (((x * 4) & 0xFFF) << 0xC) | ((y * 4) & 0xFFF);
        *((s32 *) (((char *) var_a2) + 0x14)) = 0x04000200;
        var_a1 = (((x + glyph[2]) * 4) & 0xFFF) << 0xC;
    } else {
        var_a2 = sCursor;
        sCursor = var_a2 + 8;
        sCursor = var_a2 + 0x10;
        *((s32 *) (((char *) var_a2) + 8)) = 0xE1000000;
        *((s32 *) (((char *) var_a2) + 0xC)) = t3 << 0x10;
        sCursor = var_a2 + 0x18;
        *((s32 *) (((char *) var_a2) + 0x10)) = 0xF1000000;
        *((s32 *) (((char *) var_a2) + 4)) = (((x * 4) & 0xFFF) << 0xC) | ((y * 4) & 0xFFF);
        *((s32 *) (((char *) var_a2) + 0x14)) = 0x04000400;
        var_a1 = (((x + glyph[2]) * 4) & 0xFFF) << 0xC;
    }
    *var_a2 = var_a1 | (((y * 4 + 32) & 0xFFF) | 0xE4000000);
}
'''


def _by_family(source, name):
    out = {}
    for family, text in g.variants(source, name):
        out.setdefault(family, text)
    return out


def test_a_texture_load_becomes_the_sdk_macros_on_a_gfx_cursor():
    out = _by_family(DRAFT, 'f')['gbi_macro_commands']
    assert 'extern Gfx *sCursor;' in out
    body = out[out.index('void f'):]
    assert 'gDPSetTextureImage(sCursor++, 4, 2, 1, gTex);' in body
    assert 'gDPSetTile(sCursor++, 4, 2, 0, 0, 7, 0, 3, 0, 0, 3, 0, 0);' in body
    assert 'gDPLoadSync(sCursor++);' in body
    assert 'gDPPipeSync(sCursor++);' in body
    assert 'gDPSetTileSize(sCursor++, 0, 0, 0, w * 4, h * 4);' in body
    assert 'gDPSetPrimColor(sCursor++, 0, 0, gTex >> 0x18, gTex >> 16, gTex >> 8, gTex);' in body
    # the other-mode command decodes as F3DEX2's G_SETOTHERMODE_H: shift 14, two bits
    assert 'gSPSetOtherMode(sCursor++, 0xe3, 14, 2, lrs << 3);' in body
    assert 'temp_v1 = sCursor' not in body and 'sCursor = temp' not in body
    # the value computed between the words is still computed, before the macros that use it
    assert body.index('lrs = (w * h)') < body.index('gDPSetTextureImage')


def test_every_variant_writes_the_words_the_draft_wrote():
    families = _by_family(DRAFT, 'f')
    assert {'gbi_macro_commands', 'gbi_macro_local', 'gbi_raw_commands'} <= set(families)
    assert 'gRawWords(sCursor++, 0xFD900000, gTex);' in families['gbi_raw_commands']
    assert '{ Gfx *gfx = sCursor;' in families['gbi_macro_local'] and 'sCursor = gfx; }' in families['gbi_macro_local']


def test_a_rectangle_hoisted_past_the_join_is_written_whole_in_each_arm():
    out = _by_family(RECTANGLE, 'r')['gbi_macro_commands']
    body = out[out.index('void r'):]
    assert body.count('gSPTextureRectangle(sCursor++, x * 4, y * 4, (x + glyph[2]) * 4, y * 4 + 32, 0, t3, 0, 0x400, 0x200);') == 1
    assert 'gSPTextureRectangle(sCursor++, x * 4, y * 4, (x + glyph[2]) * 4, y * 4 + 32, 0, t3, 0, 0x400, 0x400);' in body
    assert '*var_a2 =' not in body and 'var_a1 =' not in body


def test_a_field_the_macro_would_mask_differently_stays_raw_words():
    # lrs of a block load: the macro writes MIN(lrs, 2047), so only a known value passes through it unchanged
    source = DRAFT.replace('0xE3001001', '0xF3000000').replace('lrs << 3', '((w & 0xFFF) << 12) | 7')
    out = _by_family(source, 'f')['gbi_macro_commands']
    assert 'gRawWords(sCursor++, 0xF3000000, ((w & 0xFFF) << 12) | 7);' in out
    # an unmasked value in a low field could spill into the next one: raw too
    source = DRAFT.replace('((h * 4) & 0xFFF)', '(h * 4)')
    out = _by_family(source, 'f')['gbi_macro_commands']
    assert 'gRawWords(sCursor++, 0xF2000000, (((w * 4) & 0xFFF) << 0xC) | (h * 4));' in out


def test_a_call_ends_a_run_and_stays_between_the_commands():
    # the callee could read the cursor: the second read starts its own run, and each run is written on its side
    source = DRAFT.replace('    lrs = (w * h) & 0x7FF;', '    lrs = g2(w) & 0x7FF;')
    body = _by_family(source, 'f')['gbi_macro_commands']
    assert body.index('gDPLoadSync(sCursor++);') < body.index('g2(w)') < body.index('gDPPipeSync(sCursor++);')
    # and a call inside a run's words leaves that run alone
    source = DRAFT.replace('    *((s32 *) (((char *) temp_v1) + 0x14)) = 0;', '    g2(0);\n    *((s32 *) (((char *) temp_v1) + 0x14)) = 0;')
    assert all('gDPLoadSync' not in text for text in _by_family(source, 'f').values())


def test_an_existing_gfx_record_with_plain_words_is_used_as_it_is():
    source = 'typedef struct { s32 w0; s32 w1; } Gfx;\n' + DRAFT
    out = _by_family(source, 'f')['gbi_macro_commands']
    assert 'typedef union' not in out and '_g->w0 = ' in out and '->words.' not in out


HOST = '''#include <stdio.h>
#include <string.h>
typedef int s32; typedef unsigned int u32; typedef unsigned char u8; typedef unsigned short u16;
s32 *sCursor; s32 gTex = 0x12345678; u32 buffer[64];
s32 g2(s32 v) { return v; }
'''


@pytest.mark.skipif(not shutil.which('cc'), reason='no host C compiler')
@pytest.mark.parametrize('source, name, calls', [
    (DRAFT, 'f', ['f(5, 7)', 'f(0x7FF, 0x3FF)', 'f(-3, 1)']),
    (RECTANGLE, 'r', ['r(5, 7, 1, glyph)', 'r(0x3FF, 0x2FF, 0, glyph)']),
])
def test_the_variants_write_the_same_display_list_as_the_draft(tmp_path, source, name, calls):
    """Each variant compiled for the host writes the same words to the same places as the draft (the draft's
    pointer arithmetic is m2c's, in bytes, so the host version spells its locals as `char *`)."""
    def run(text, label):
        text = re.sub(r'\bs32 \*(temp_\w+|var_a2)\b', r'char *\1', text).replace('*var_a2 =', '*(s32 *) var_a2 =')
        text = text.replace('extern s32 *sCursor;', '').replace('extern s32 gTex;', '')
        main = 'u8 glyph[4] = {3, 4, 5, 6};\nint main(void) {\n'
        for call in calls:
            main += f'    memset(buffer, 0, sizeof buffer); sCursor = (void *) buffer; {call};\n'
            main += '    for (int i = 0; i < 64; i++) printf("%08x ", buffer[i]); printf("%ld\\n", (long) ((char *) sCursor - (char *) buffer));\n'
        main += '    return 0;\n}\n'
        prefix = HOST if 'Gfx' not in text else HOST.replace('s32 *sCursor;', '')
        body = text.replace('extern Gfx', 'Gfx')
        path = tmp_path / f'{label}.c'
        path.write_text(prefix + body + main)
        binary = tmp_path / label
        subprocess.run(['cc', '-w', '-Wno-error', '-Wno-incompatible-pointer-types', '-Wno-int-conversion', '-o', str(binary), str(path)], check=True)
        return subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout
    expected = run(source, 'draft')
    variants = g.variants(source, name)
    assert variants
    for k, (family, text) in enumerate(variants):
        assert run(text, f'variant{k}') == expected, family
    assert os.path.exists(tmp_path / 'draft')
