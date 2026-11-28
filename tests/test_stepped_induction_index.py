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


def _walked(start, *, declare='', before='', body=''):
    """SOURCE with a third stepped variable, `extra`, started at `start`."""
    return (SOURCE.replace('    s32 *slot;\n', f'    s32 *slot;\n    s32 extra;\n{declare}')
            .replace('    i = 0;\n', f'    i = 0;\n{before}    extra = {start};\n')
            .replace('        i += 1;\n', f'        use(extra);\n{body}        i += 1;\n')
            .replace('        off += 0xC;\n', '        off += 0xC;\n        extra += 4;\n'))


def _indexed_extra(source):
    return [text for _, text in variants(source, 'walk') if 'extra += 4;' not in text]


def test_a_start_proven_the_same_on_every_pass_is_repeated():
    assert 'use((arg0 + i * 4));' in _indexed_extra(_walked('arg0'))[0]


def test_a_global_dereference_or_call_start_is_never_repeated():
    for start in ('D_value', '*out', 'next(arg0)', '(s32)*out', 'slot[1]', 'M2C_FIELD(arg0, s32 *, 8)'):
        source = _walked(start)
        assert _indexed_extra(source) == [], start
        # the cursors with a proven start are still offered; this one stays stepped
        assert variants(source, 'walk') and all(f'extra = {start};' in text for _, text in variants(source, 'walk'))


def test_a_local_something_else_could_write_is_not_repeated():
    for declare, before, body in (('    s32 moved;\n', '    keep(&moved);\n', ''),
                                  ('    extern s32 moved;\n', '', ''),
                                  ('    s32 moved;\n', '', '        moved = 1;\n')):
        assert _indexed_extra(_walked('moved', declare=declare, before=before, body=body)) == [], (declare, body)


def test_nothing_is_offered_when_the_counter_is_written_again_or_started_outside_an_outer_loop():
    assert variants(SOURCE.replace('        i += 1;\n', '        i = next(i);\n        i += 1;\n'), 'walk') == []
    outer = SOURCE.replace('    do {\n', '    while (more()) {\n    do {\n').replace(
        '>= 0);\n', '>= 0);\n    }\n')
    assert variants(outer, 'walk') == []
