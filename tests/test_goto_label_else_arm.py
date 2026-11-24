"""goto_label_else_arm: an early arm that `goto`s a label at the end of the code after it, written as that code's
`else` with the label's run copied. A KMC GCC 2.7.2 collision routine: 24406 -> 22230 for one site, 18762 for both
(the target's `bnel` to the hit block placed after the other path). The source below is made up; it only has that
shape."""
from decomprepair import goto_label_else_arm as arm
from decomprepair import registry

SOURCE = """extern s32 hit(f32 *);
extern void push(f32 *);
void f(f32 *p, f32 r, s32 *flag) {
    f32 d;
    f32 v;
    if (r > 0.0f) {
        if ((hit(p) << 0x18) != 0) {
            v = p[0] + r;
            *flag = 1;
            goto join;
        }
        d = p[1] - r;
        if (d < r) {
            push(p);
            v = p[0] + d;
            *flag = 2;
        join:
            p[2] = v;
        }
    }
}
"""


def children(source):
    return [text for _, text in arm.variants(source, 'f')]


def test_the_hit_arm_becomes_the_else_with_the_join_copied():
    texts = children(SOURCE)
    assert texts
    text = texts[0]
    assert 'goto join' not in text and 'join:' not in text
    assert text.count('p[2] = v;') == 2
    assert text.index('d = p[1] - r;') < text.index('else') < text.index('v = p[0] + r;')
    assert '(hit(p) << 0x18) == 0' in text
    assert text.count('{') == text.count('}')
    assert any('!((hit(p) << 0x18) != 0)' in t for t in texts)


def test_code_after_the_join_block_stops_it():
    """Falling out of the label's run must end where the `goto` ends: a statement after its block would run on one path
    only."""
    assert not children(SOURCE.replace('            p[2] = v;\n        }\n', '            p[2] = v;\n        }\n        r = 0;\n'))


def test_two_sites_are_offered_together_first():
    body = SOURCE.split('{', 1)[1].rsplit('}', 1)[0]
    block = body.split('    f32 v;\n', 1)[1]
    both = SOURCE.replace(block, block + block.replace('join', 'join2'))
    texts = children(both)
    assert len(texts) >= 3 and 'goto' not in texts[0]
    assert texts[0].count('p[2] = v;') == 4


def test_it_is_declared_in_the_registry():
    assert 'goto_label_else_arm' in {r.module.rsplit('.', 1)[-1] for r in registry.declared()}
