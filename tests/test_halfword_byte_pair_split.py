"""A halfword built from two bytes, written as two statements on a halfword local that is passed on."""
from decomprepair.halfword_byte_pair_split import FAMILY, variants

# A sound-engine note starter (KMC GCC 2.7.2, 105 -> 0): the saved best, with m2c's cast and wrapper.
SAVED = '''static __inline__ s32 __repair_inline(s32 a) { return a; }
s32 g();
s32 f(void *arg0, void *arg1) {
    s32 id;
    u32 table;
    id = (u16)(__repair_inline(*(u8 *)arg1 | (*(u8 *)((char *)arg1 + 7) << 8)));
    if (id != 0) {
        table = g();
        if (table != 0) {
            return 1;
        }
    }
    return 0;
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_matched_combination_is_one_child():
    out = [_squash(src) for fam, src in variants(SAVED, 'f') if fam == FAMILY]
    want = ('u16 id; u32 table; id = *(u8 *)arg1; id |= (*(u8 *)((char *)arg1 + 7)) << 8; '
            'if (id != 0) { table = g(id);')
    assert any(want in s for s in out)


def test_each_edit_is_also_a_child_on_its_own():
    out = [_squash(src) for _, src in variants(SAVED, 'f')]
    assert any('id |= ' in s and 's32 id;' in s and 'g(id)' not in s for s in out)
    assert any('u16 id;' in s and 'g(id)' not in s for s in out)
    assert any('id |= ' in s and 'g(id)' in s and 's32 id;' in s for s in out)


def test_the_shifted_operand_first_is_offered_too():
    out = [_squash(src) for _, src in variants(SAVED, 'f')]
    assert any('id = (*(u8 *)((char *)arg1 + 7)) << 8; id |= *(u8 *)arg1;' in s for s in out)


def test_a_shifted_operand_written_first_is_read_the_same():
    src = SAVED.replace('*(u8 *)arg1 | (*(u8 *)((char *)arg1 + 7) << 8)', '(*(u8 *)((char *)arg1 + 7) << 8) | *(u8 *)arg1')
    assert any('id = *(u8 *)arg1; id |= (*(u8 *)((char *)arg1 + 7)) << 8;' in _squash(s) for _, s in variants(src, 'f'))


def test_a_prototyped_callee_gets_no_argument():
    src = SAVED.replace('s32 g();', 's32 g(s32);').replace('g()', 'g(1)')
    assert not any('g(id)' in s for _, s in variants(src, 'f'))


def test_other_statements_are_left_alone():
    base = 'void f(u8 *p, s32 k) {\n    s32 v;\n    %s\n    G(v);\n}\n'
    for body in ('v = p[0] | p[1];',                 # no shift
                 'v = p[0] | (p[1] << 8) | k;',      # three operands
                 'v = v | (p[1] << 8);',             # reads itself
                 'v = k ? p[0] | (p[1] << 8) : 0;'): # conditional
        assert variants(base % body, 'f') == [], body
    assert variants('void f(volatile u8 *p) { s32 v; v = p[0] | (p[1] << 8); G(v); }', 'f') == []
