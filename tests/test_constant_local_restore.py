from decomprepair.constant_local_restore import FAMILY, variants

SOURCE = """void f(void *arg0) {
    s32 *base;
int __repair_constant = 2;
    u16 id;

    id = g(arg0);
    (*(s8 *)((char *)(arg0) + 0x7A)) = __repair_constant;
    (*(s8 *)((char *)(arg0) + 0x74)) = (int)__repair_constant;
    (*(s32 *)((char *)(arg0) + 0x38)) = id & __repair_constant;
}
"""


def children(source):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_a_stored_constant_local_is_written_as_its_literal():
    [child] = children(SOURCE)
    assert '__repair_constant' not in child
    assert '+ 0x7A)) = 2;' in child and '= (int)2;' in child and 'id & 2;' in child


def test_assigned_once_and_every_local_at_once():
    source = """void f(s32 *p) {
    s32 one;
    u32 two = 2;
    one = 1;
    p[0] = one;
    p[1] = two;
}
"""
    first, *rest = children(source)
    assert 'p[0] = 1;' in first and 'p[1] = 2U;' in first and 'one' not in first
    assert len(rest) == 2


def test_a_local_that_changes_or_is_addressed_or_does_not_fit_is_left():
    for body in ('int k = 2; k++; p[0] = k;', 'int k = 2; k = 3; p[0] = k;', 'int k = 2; g(&k); p[0] = k;',
                 'int k = 2; p[0] = k; k += 1;', 'volatile int k = 2; p[0] = k;', 's8 k = 200; p[0] = k;',
                 'int k; p[0] = k; k = 2;', 'int k = h(); p[0] = k;', 'int k = 2; { int k = 3; p[0] = k; }'):
        assert children('void f(s32 *p) {\n    ' + body.replace('; ', ';\n    ') + '\n}\n') == [], body
