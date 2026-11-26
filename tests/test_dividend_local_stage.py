"""dividend_local_stage: a power-of-two division's dividend staged in a local of its own, new or dead there.

Synthetic shape of a 320-instruction SN64 GCC 2.8.1 options menu (100 -> 85): the colour
`0xFF - ((cos * 127 >> 15) + 0x80) / 2` took the target's registers once the dividend went into the clamp's local,
which is dead at that point."""
from decomprepair import dividend_local_stage as s

SOURCE = '''void menu(s32 *o) {
    s32 buf[4];
    s32 i;
    s32 shade;
    s32 level;

    shade = 0xFF - ((((s16) wave(o[1] * 400) * 127) >> 15) + 0x80) / 2;
    tint(shade, shade, shade);
    for (i = 0; i < 2; i++) {
        if (o[i]) {
            level = o[i + 2];
            if (level > 100) {
                level = 100;
            }
            o[i + 2] = level;
        }
    }
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'menu') if family == s.FAMILY]


def test_a_new_local_and_each_dead_local():
    texts = _texts()
    staged = {t.split(' = (((s16)')[0].split('\n')[-1].strip() for t in texts}
    assert staged == {'stg', 'level', 'i'}  # i is set by the for before any read: dead here too
    new = next(t for t in texts if 'stg = ' in t)
    assert '    s32 stg;\n' in new
    assert 'stg = (((s16) wave(o[1] * 400) * 127) >> 15) + 0x80;\n    shade = 0xFF - stg / 2;' in new
    dead = next(t for t in texts if 'level = (((s16)' in t)
    assert 'shade = 0xFF - level / 2;' in dead and dead.count('s32 level;') == 1


def test_live_locals_and_locals_the_statement_names_are_not_used():
    assert not any('shade = 0xFF - shade / 2' in t for t in _texts())
    # level read after the statement (the clamp keeps it) is live there: not offered
    live = SOURCE.replace('    tint(shade, shade, shade);', '    tint(shade, shade, level);')
    assert not any('level = (((s16)' in t for t in _texts(live))


def test_only_power_of_two_divisions_of_a_parenthesised_dividend():
    assert _texts(SOURCE.replace(') / 2;', ') / 3;')) == []
    assert _texts(SOURCE.replace('    shade = 0xFF - ((((s16) wave(o[1] * 400) * 127) >> 15) + 0x80) / 2;',
                                 '    shade = 0xFF - wave(o[1]) / 2;')) == []


def test_side_effects_outside_the_dividend_decline():
    source = SOURCE.replace('    shade = 0xFF - (', '    shade = bump() - (')
    assert _texts(source) == []
