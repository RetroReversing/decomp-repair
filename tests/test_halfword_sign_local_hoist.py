"""halfword_sign_local_hoist: the `(s16)` copy of a halfword counter taken right after the counter is read.

Reduced from a KMC N64 object update (285 -> 0 with other families' parts): the copy sits after the statement that
stores the counter back, as in the matched source."""
from decomprepair import halfword_sign_local_hoist as h

COPY = '''void f(void *arg0) {
    u16 t;
    s32 n;
    void *p;

    t = M2C_FIELD(arg0, u16 *, 0xC);
    M2C_FIELD(arg0, u16 *, 0xC) = (u16) (t + 1);
    p = M2C_FIELD(arg0, void **, 0x10);
    g(p);
    n = (s16) t;
    if (n == 0xF) {
        g(p);
    }
}
'''
RAW = COPY.replace('    n = (s16) t;\n    if (n == 0xF)', '    if ((s16) t == 0xF)').replace('        g(p);\n    }\n}', '        g(p);\n    }\n    if ((s16) t == 0x1E) {\n        g(p);\n    }\n}')


def _by(source, family):
    return [text for fam, text in h.variants(source, 'f') if fam == family]


def test_existing_copy_moves_up_after_the_store():
    texts = _by(COPY, h.COPY)
    assert len(texts) == 2
    body = texts[1].split('{', 1)[1].splitlines()
    assert [row.strip() for row in body if 'n = (s16) t' in row] and body.index('    n = (s16) t;') == \
        body.index('    M2C_FIELD(arg0, u16 *, 0xC) = (u16) (t + 1);') + 1
    assert texts[1].count('n = (s16) t;') == 1


def test_two_raw_narrowings_share_one_word_local():
    texts = _by(RAW, h.NAMED)
    assert len(texts) == 2
    assert '    s32 t_s16;\n' in texts[1] and 'if (t_s16 == 0xF)' in texts[1] and 'if (t_s16 == 0x1E)' in texts[1]
    assert '(s16) t ==' not in texts[1]


def test_a_reassigned_counter_stops_the_copy_moving():
    assert _by(COPY.replace('    g(p);\n    n =', '    t = 2;\n    n ='), h.COPY) == []


def test_a_single_narrowing_is_not_named():
    assert _by(RAW.replace('(s16) t == 0x1E', 'k == 0x1E'), h.NAMED) == []
