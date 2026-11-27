"""post_loop_counter_stage: an accumulator's post-loop read staged in the loop's counter.

A synthetic shape of an N64 checksum check (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O1 -g`): with `sum = 0; for (i = 0;
...)` cse made the counter's zero the accumulator's register (the accumulator lives longer), so the zeros came out in
the other order; `i = sum & 0xFF; if (i != expect)` after the loop matched (5 -> 0, and 10 -> 0)."""
from decomprepair import post_loop_counter_stage as s
from decomprepair import registry

SOURCE = '''s32 check(u8 *buf, u16 len, u8 expect) {
    s32 i;
    s32 sum;
    s32 result;

    sum = 0;
    for (i = 0; i < (len & 0xFFFF); i++) {
        sum += buf[i];
    }
    if ((sum & 0xFF) != expect) { result = 0; } else { result = len & 0xFFFF; }
    return result;
}
'''


def _texts(source=SOURCE, name='check'):
    return [text for family, text in s.variants(source, name) if family == s.FAMILY]


def test_the_masked_read_is_staged_in_the_counter_first():
    first = _texts()[0]
    assert '    i = sum & 0xFF;\n    if (i != expect) { result = 0; }' in first
    assert 'sum += buf[i];' in first


def test_the_bare_read_is_offered_too():
    assert any('i = sum;\n    if ((i & 0xFF) != expect)' in text for text in _texts())


def test_a_counter_read_after_the_loop_is_left_alone():
    source = SOURCE.replace('return result;', 'return result + i;')
    assert _texts(source) == []


def test_a_counter_set_again_later_is_fine():
    source = SOURCE.replace('return result;', 'i = 3;\n    return result + i;')
    assert _texts(source)


def test_the_statement_must_read_the_accumulator():
    source = SOURCE.replace('if ((sum & 0xFF) != expect)', 'if (expect != 0)')
    assert _texts(source) == []


def test_a_value_the_loop_does_not_update_is_no_accumulator():
    source = SOURCE.replace('sum += buf[i];', 'buf[i] = sum;')
    assert _texts(source) == []


def test_it_declares_itself():
    assert s.FAMILY in {family for repair in registry.declared() for family in repair.families}


def test_an_accumulate_through_a_temporary_counts():
    source = SOURCE.replace('    s32 result;\n', '    s32 result;\n    s32 t;\n').replace(
        'sum += buf[i];', 't = buf[i] + sum; sum = t;')
    assert any('i = sum & 0xFF;' in text for text in _texts(source))
