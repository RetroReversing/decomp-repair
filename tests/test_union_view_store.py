"""A float stored as a word through a block-scoped union, written as the plain float store."""
from decomprepair import union_view_store as p

SOURCE = '''void f(void *arg0, f32 a, f32 b) {
    f32 t;

    t = a * b;
    { union { f32 f; int i; } v; v.f = t * a; *(int *)((char *)arg0 + 4) = v.i; }
    (*(f32 *)((char *)(arg0) + 8)) = t;
}
'''


def test_the_union_store_becomes_a_plain_float_store():
    ((family, text),) = p.variants(SOURCE, 'f')
    assert family == p.FAMILY
    assert '*(f32 *)((char *)arg0 + 4) = t * a;' in text
    assert 'union' not in text
    assert '(*(f32 *)((char *)(arg0) + 8)) = t;' in text


def test_each_store_is_a_child_and_all_together_too():
    source = SOURCE.replace('    (*(f32 *)((char *)(arg0) + 8)) = t;',
                            '    { union { f32 f; u32 i; } w; w.f = t; *(u32 *)((char *)arg0 + 8) = w.i; }')
    kids = [text for _, text in p.variants(source, 'f')]
    assert len(kids) == 3
    assert [k.count('union') for k in kids] == [1, 1, 0]


def test_a_union_that_is_read_again_is_left_alone():
    source = SOURCE.replace('v.f = t * a;', 'v.f = t * a + v.f;')
    assert p.variants(source, 'f') == []


def test_a_word_stored_from_the_wrong_member_is_left_alone():
    source = SOURCE.replace('= v.i;', '= v.f;')
    assert p.variants(source, 'f') == []


def test_a_call_in_the_value_is_evaluated_once_either_way():
    source = SOURCE.replace('v.f = t * a;', 'v.f = sinApprox(a);')
    ((_, text),) = p.variants(source, 'f')
    assert '*(f32 *)((char *)arg0 + 4) = sinApprox(a);' in text


def test_a_store_through_a_byte_offset_of_zero_keeps_the_address():
    source = SOURCE.replace(' + 4)', ')')
    ((_, text),) = p.variants(source, 'f')
    assert '*(f32 *)((char *)arg0) = t * a;' in text


def test_the_module_declares_itself():
    from decomprepair import registry
    assert 'union_view_store' in {r.module for r in registry.declared()}
