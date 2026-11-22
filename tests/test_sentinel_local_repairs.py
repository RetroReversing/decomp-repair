from decomprepair import sentinel_local_repairs as sentinel

SOURCE = '''s32 g(s32);
s32 f(s32 a, s32 b)
{
    s32 v;
    v = g(a);
    if (v == -1) {
        b = g(b);
    }
    if (b != (-1)) {
        return b;
    }
    if (0xFF == a) {
        return 0;
    }
    return v;
}
'''


def test_two_compares_of_one_literal_share_a_local_and_each_gets_a_private_one():
    out = sentinel.variants(SOURCE, 'f')
    shared = [text for family, text in out if family == sentinel.SHARED]
    split = [text for family, text in out if family == sentinel.SPLIT]
    assert len(shared) == 1 and len(split) == 2
    assert '  s32 sentinel_neg0 = -1;' in shared[0]
    assert 'v == sentinel_neg0' in shared[0] and 'b != sentinel_neg0' in shared[0]
    assert '0xFF == a' in shared[0]  # a literal compared once is left alone
    assert all('sentinel_neg1' in text and 'sentinel_neg0' in text for text in split)
    assert {text.count('sentinel_neg1') for text in split} == {2}  # declaration plus the one compare apart


def test_the_new_declaration_comes_before_the_existing_ones():
    text = sentinel.variants(SOURCE, 'f')[0][1]
    assert text.index('sentinel_neg0 = -1') < text.index('s32 v;')


def test_nothing_is_proposed_for_a_single_compare_or_for_zero():
    assert sentinel.variants('void f(int a)\n{\n    if (a == -1) {\n        g();\n    }\n}\n', 'f') == []
    assert sentinel.variants('void f(int a, int b)\n{\n    if (a == 0 || b != 0) {\n        g();\n    }\n}\n', 'f') == []


def test_an_existing_name_is_not_reused():
    source = SOURCE.replace('s32 v;', 's32 v;\n    s32 sentinel_neg0;')
    assert 's32 sentinel_neg1 = -1;' in sentinel.variants(source, 'f')[0][1]
