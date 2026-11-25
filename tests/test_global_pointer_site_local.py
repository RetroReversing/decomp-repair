"""A global pointer read at two sites through one shared local, the first site in a one-shot scope with its calls
(an N64 loader, SN64 GCC 2.8.1, 7510 -> 0)."""
from decomprepair.global_pointer_site_local import FAMILY, variants

SOURCE = """extern u8 *gRecord;
extern s32 gCount;

s32 load(s32 arg0, char *name)
{
    u8 *lvl;
    s32 i;

    reset();
    FLD(gRecord, s32, 0xC0) = 2;
    lvl = lookup(arg0);
    for (i = 0; i < gCount; i++) {
        if (match(name, i) == 0) {
            FLD(gRecord, s32, 0xD8) = FLD(gRecord, s32, 0x9C);
            break;
        }
    }
    return lvl != 0;
}
"""


def test_shared_local_at_every_site_and_the_scoped_first_site():
    found = variants(SOURCE, 'load')
    assert found and all(family == FAMILY for family, _ in found)
    texts = [text for _, text in found]
    plain = texts[0]
    assert '{\n    u8 *pgRecord;\n    u8 *lvl;' in plain
    assert '    pgRecord = gRecord;\n    FLD(pgRecord, s32, 0xC0) = 2;\n' in plain
    assert ('            pgRecord = gRecord;\n            FLD(pgRecord, s32, 0xD8) = FLD(pgRecord, s32, 0x9C);\n'
            in plain)
    scoped = ('    do {\n        reset();\n        pgRecord = gRecord;\n        FLD(pgRecord, s32, 0xC0) = 2;\n'
              '        lvl = lookup(arg0);\n    } while (0);\n')
    match = [text for text in texts if scoped in text]
    assert len(match) == 1
    assert 'FLD(pgRecord, s32, 0xD8) = FLD(pgRecord, s32, 0x9C);' in match[0]


def test_break_and_control_lines_never_enter_a_scope_and_one_site_is_left_alone():
    texts = [text for _, text in variants(SOURCE, 'load')]
    assert all('break;\n            } while (0);' not in text for text in texts)
    assert all('    for (i = 0; i < gCount; i++) {\n' in text for text in texts)
    assert variants(SOURCE.replace('FLD(gRecord, s32, 0xC0) = 2;\n', ''), 'load') == []


def test_a_global_that_is_assigned_is_not_a_read_site():
    source = SOURCE.replace('FLD(gRecord, s32, 0xC0) = 2;', 'gRecord = 0;')
    assert variants(source, 'load') == []
