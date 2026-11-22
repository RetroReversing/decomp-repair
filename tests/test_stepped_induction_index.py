from decomprepair.stepped_induction_index import FAMILY, FLAG, probes, variants

SOURCE = """
void walk(void *arg0, s32 *out) {
    s32 i;
    s32 off;
    char *cursor;
    void *base;
    s32 *slot;
    slot = M2C_FIELD(arg0, s32 *, 0x10);
    i = 0;
    off = 0;
    cursor = (char *) slot;
    base = M2C_FIELD(arg0, void *, 0x14);
    do {
        out[i] = *(s32 *) cursor + off;
        out[i + 1] = M2C_FIELD(base, s32 *, 4);
        i += 1;
        cursor += 0x20;
        off += 0xC;
    } while (*(s16 *) cursor >= 0);
}
"""


def test_every_stepped_variable_becomes_a_multiple_of_the_counter():
    first = variants(SOURCE, 'walk')[0]
    assert first[0] == FAMILY
    text = first[1]
    assert 'out[i] = *(s32 *) ((char *)((char *) slot) + i * 0x20) + (i * 0xc);' in text
    assert '} while (*(s16 *) ((char *)((char *) slot) + i * 0x20) >= 0);' in text
    assert 'cursor +=' not in text and 'off +=' not in text and 'cursor = ' not in text and 'off = 0;' not in text
    assert '        i += 1;\n' in text
    assert variants(text, 'walk') == []


def test_each_variable_alone_is_offered_too():
    result = [text for _, text in variants(SOURCE, 'walk')]
    assert len(result) == 3
    assert any('off +=' not in t and 'cursor += 0x20;' in t for t in result)
    assert any('cursor +=' not in t and 'off += 0xC;' in t for t in result)


def test_leaves_variables_that_change_inside_start_elsewhere_or_live_on():
    # a counter that starts at 1, a step before a use, a use after the loop, a reassignment inside
    assert variants(SOURCE.replace('    i = 0;\n', '    i = 1;\n'), 'walk') == []
    after = SOURCE.rstrip().rstrip('}') + '    out[9] = off;\n}\n'
    assert all('off += 0xC;' in text for _, text in variants(after, 'walk') if 'off = 0;' in text)
    assert all('cursor = base;' in text for _, text in variants(SOURCE.replace(
        '        out[i] = *(s32 *) cursor + off;', '        cursor = base;\n        out[i] = off;'), 'walk') if 'cursor +=' not in text)
    assert variants(SOURCE.replace('        i += 1;\n        cursor += 0x20;\n        off += 0xC;\n',
                                   '        cursor += 0x20;\n        out[0] = 0;\n        i += 1;\n        off += 0xC;\n'), 'walk') != [] and all(
        'cursor += 0x20;' in text for _, text in variants(SOURCE.replace(
            '        i += 1;\n        cursor += 0x20;\n        off += 0xC;\n',
            '        cursor += 0x20;\n        out[0] = 0;\n        i += 1;\n        off += 0xC;\n'), 'walk'))


def test_the_probe_drops_the_flag_and_only_then():
    fn = {'best_source': SOURCE, 'name': 'walk'}
    proj = {'arch': 'mips'}
    profile = {'toolchain': 'gcc-2.7.2-kmc', 'flags': ['-G0', '-O2', FLAG]}
    [(flags, text), *_] = probes(proj, fn, profile)
    assert FLAG not in flags and flags == ['-G0', '-O2'] and 'i * 0x20' in text
    assert probes(proj, fn, {'toolchain': 'gcc-2.7.2-kmc', 'flags': ['-O2']}) == []
    assert probes(proj, fn, dict(profile, toolchain='ido-7.1')) == []
