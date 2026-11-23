"""clamp_then_chain: `if (c) x = C; else x = v;` (or `x = v; if (c) x = C;`) with the constant arm written `x = v = C`.

Synthetic shape of the last clamp of a 172-instruction KMC sound-voice starter (15 -> 0): jump.c hoisted the one-insn
else copy above the branch, so the result could not take the flag's register; a two-insn then arm stops the hoist."""
from decomprepair import clamp_then_chain as s

SOURCE = '''void start(f32 f, s32 h) {
  u32 w;
  u16 r;
  w = (u32)(f * 8192.0f);
  if (w >= 0x4000) r = 0x3FFF; else r = w;
  send(h, r);
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'start') if family == s.FAMILY]


def test_the_if_else_clamp_gets_the_chained_constant_arm():
    assert _texts() == [SOURCE.replace('r = 0x3FFF; else r = w;', 'r = w = 0x3FFF; else r = w;')]


def test_the_copy_form_is_written_as_the_chained_if_else():
    source = SOURCE.replace('  if (w >= 0x4000) r = 0x3FFF; else r = w;\n', '  r = w;\n  if (w >= 0x4000) { r = 0x3FFF; }\n')
    texts = _texts(source)
    assert len(texts) == 1
    assert 'if (w >= 0x4000) r = w = 0x3FFF; else r = w;' in texts[0] and '  r = w;\n' not in texts[0]


def test_a_value_read_after_the_clamp_is_left_alone():
    assert _texts(SOURCE.replace('send(h, r);', 'send(h, r + w);')) == []


def test_a_value_reassigned_after_the_clamp_is_still_dead():
    source = SOURCE.replace('send(h, r);', 'send(h, r);\n  w = 3;\n  send(h, w);')
    assert len(_texts(source)) == 1


def test_each_site_alone_and_all_together():
    source = SOURCE.replace('send(h, r);', 'send(h, r);\n  w = (u32)f;\n  if (w >= 0x80) r = 0x7F; else r = w;\n  send(h, r);')
    texts = _texts(source)
    assert len(texts) == 3
    assert sum(t.count('= w = ') for t in texts) == 4


def test_a_non_constant_arm_or_an_unrelated_test_is_left_alone():
    assert _texts(SOURCE.replace('r = 0x3FFF;', 'r = h;')) == []
    assert _texts(SOURCE.replace('if (w >= 0x4000)', 'if (h >= 0x4000)')) == []
