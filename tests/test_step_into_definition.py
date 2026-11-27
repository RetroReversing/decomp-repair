"""A later `v = v + K;` written in the statement that set `v`."""
from decomprepair.step_into_definition import FAMILY, variants

SAVED = '''void f(void *arg0, void *part) {
    u16 w;
    if (part != 0) {
        w = M2C_FIELD(arg0, u16 *, 0x6A);
        M2C_FIELD(part, s32 *, 0x80) = 0x3F1;
        M2C_FIELD(part, u8 *, 0x75) = 0;
        w = w + 2;
        M2C_FIELD(part, u16 *, 0x6A) = (s16) w;
    }
}
'''


def _children(source):
    return [' '.join(text.split()) for family, text in variants(source, 'f') if family == FAMILY]


def test_the_step_moves_into_the_load():
    out = _children(SAVED)
    assert len(out) == 1
    assert 'w = M2C_FIELD(arg0, u16 *, 0x6A) + 2; M2C_FIELD(part, s32 *, 0x80)' in out[0]
    assert 'w = w + 2' not in out[0]


def test_other_spellings_and_parentheses():
    out = _children('''void f(int a, int b) {
    int v;
    int u;
    v = a | b;
    g(a);
    v++;
    u = a;
    u <<= 3;
    g(v + u);
}
''')
    assert any('v = (a | b) + 1; g(a); u = a;' in text for text in out)
    assert any('u = a << 3; g(v + u);' in text and 'v = (a | b) + 1;' in text for text in out)  # every site


def test_a_use_between_is_left_alone():
    assert variants(SAVED.replace('M2C_FIELD(part, u8 *, 0x75) = 0;', 'M2C_FIELD(part, u8 *, 0x75) = w;'), 'f') == []


def test_a_branch_between_is_left_alone():
    assert variants(SAVED.replace('M2C_FIELD(part, u8 *, 0x75) = 0;', 'if (part) { g(); }'), 'f') == []


def test_an_address_taken_local_is_left_alone():
    assert variants(SAVED.replace('M2C_FIELD(part, u8 *, 0x75) = 0;', 'g(&w);'), 'f') == []


def test_a_global_is_left_alone():
    assert variants(SAVED.replace('    u16 w;\n', ''), 'f') == []
