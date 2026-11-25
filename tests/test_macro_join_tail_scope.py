"""A brace macro split after its last conditional, the tail wrapped with the rest of its arm (and the enclosing if)."""
from decomprepair import macro_join_tail_scope as tail

SOURCE = '''#define MIN(a, b) ((a) < (b) ? (a) : (b))
#define PUT(p, a, b) { (p)->w0 = (a); (p)->w1 = (b); }
#define LOAD(p, img, n, m) \\
{ \\
    PUT(p, 0xFD000000, (u32)(img)); \\
    PUT(p, 0xF3000000, MIN(n, 2047) << 12); \\
    PUT(p, 0xF5000000, (m) & 0xF); \\
    PUT(p, 0xF2000000, (n) << 2); \\
}
void call(s32);
extern Cmd *gList;
void f(u8 *img, void *pal, s32 kind, s32 n) {
    s32 mask;

    mask = 0;
    if (kind == 8) {
        if (pal != NULL) {
            LOAD(gList++, img, n, mask);
            PUT(gList++, 0xF0000000, (u32)pal);
            call(0x60);
        } else {
            LOAD(gList++, img, n, mask);
            call(0x50);
        }
    }
    if (kind == 16) {
        LOAD(gList++, img, n, mask);
        call(0x50);
    }
}
'''


def _children():
    return [text for family, text in tail.variants(SOURCE, 'f') if family == tail.FAMILY]


def test_split_is_after_the_last_statement_with_a_conditional():
    text = _children()[0]
    assert '#define LOAD_join_head(p, img, n, m) { PUT(p, 0xFD000000, (u32)(img)); PUT(p, 0xF3000000, MIN(n, 2047) << 12); }' in text
    assert '#define LOAD_join_tail(p, img, n, m) { PUT(p, 0xF5000000, (m) & 0xF); PUT(p, 0xF2000000, (n) << 2); }' in text


def test_tail_takes_the_rest_of_the_arm_and_the_enclosing_if_is_offered():
    out = _children()
    palette = ('LOAD_join_head(gList++, img, n, mask); do { LOAD_join_tail(gList++, img, n, mask);\n'
               '            PUT(gList++, 0xF0000000, (u32)pal);\n            call(0x60); } while (0);')
    assert any(palette in t and 'do { if (pal != NULL)' not in t for t in out)
    # the combination that matched: the palette arm's tail and the if/else around it, as one child
    both = [t for t in out if palette in t and 'do { if (pal != NULL)' in t]
    assert len(both) == 1 and both[0].count('} while (0);') == 2
    assert '} } while (0);\n    }\n    if (kind == 16)' in both[0]


def test_pairs_and_limits():
    out = _children()
    assert any(t.count('LOAD_join_tail(gList++') == 2 for t in out)
    assert len(out) == len(set(out)) <= tail.LIMIT
    assert all(t.count('#define LOAD_join_head') == 1 for t in out)


def test_a_macro_without_a_conditional_or_without_a_tail_is_left_alone():
    plain = SOURCE.replace('MIN(n, 2047) << 12', '(n) << 12')
    assert tail.variants(plain, 'f') == []
    last = SOURCE.replace('PUT(p, 0xF2000000, (n) << 2); \\\n', 'PUT(p, 0xF2000000, MIN(n, 9)); \\\n')
    assert tail.variants(last, 'f') == []
