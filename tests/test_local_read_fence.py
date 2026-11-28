import re

from decomprepair.local_read_fence import FAMILY, variants

SOURCE = """s32 build(Img *img, s32 x, s32 flags) {
    s32 off;
    s32 rows;
    s32 scale;
    u8 *data;

    scale = 1;
    data = img->data;
    off = 0;
    while (img->h > 0) {
        rows = img->h;
        GFX(0xFD100000, (u32)(data + off));
        GFX(0xF2000000, scale * rows);
        off += img->w * rows;
        img->h -= rows;
    }
    return off;
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_a_single_read_of_a_pointer_local_goes_through_a_fenced_scratch_copy():
    out = [_flat(text) for family, text in variants(SOURCE, 'build') if family == FAMILY]
    assert any('{ u8 *__fence_data; do { __fence_data = data; } while (0); GFX(0xFD100000, (u32)(__fence_data + off)); }'
               in text for text in out)
    assert any('do { do { __fence_data = data; } while (0); } while (0);' in text for text in out)


def test_the_assignment_of_the_local_and_non_pointer_locals_are_left_alone():
    out = [_flat(text) for _, text in variants(SOURCE, 'build')]
    assert out and all('data = img->data;' in text for text in out)
    assert not any('__fence_off' in text or '__fence_scale' in text or '__fence_rows' in text for text in out)


def test_nothing_is_offered_without_a_pointer_local():
    assert variants('s32 f(s32 a) { s32 b; b = a; g(b); return b; }', 'f') == []


def test_pointer_address_and_increment_are_not_replaced_by_a_scratch():
    source = """void f(void) {
    void *p;
    use(p);
    callback(&p);
    callback(&(p));
    callback(& /* address */ ((p)));
    consume(p++);
    consume(++p);
    consume(p--);
    consume(--p);
}
"""
    out = [text for _, text in variants(source, 'f')]
    assert not any('__fence_p' in text for text in out)
    for text in out:
        for original in ('callback(&p)', 'callback(&(p))', 'callback(& /* address */ ((p)))',
                         'consume(p++)', 'consume(++p)', 'consume(p--)', 'consume(--p)'):
            assert original in text


def test_existing_scratch_name_and_repeated_fence_are_not_shadowed():
    source = """void f(void) {
    void *p;
    void *__fence_p;
    use(p);
}
"""
    assert not any('__fence_p = p' in text for _, text in variants(source, 'f'))
    fenced = next(text for _, text in variants(SOURCE, 'build') if '__fence_data' in text)
    assert not any(text.count('u8 *__fence_data;') > fenced.count('u8 *__fence_data;')
                   for _, text in variants(fenced, 'build'))


def test_parenthesized_pointer_updates_do_not_become_scratch_updates():
    source = """void f(void) {
    void *p;
    use(p);
    consume((p)++);
    consume(++((p)));
    (p) = next();
}
"""
    out = [text for _, text in variants(source, 'f')]
    assert out and any('use(__fence_p)' in text for text in out)
    assert all('consume((p)++)' in text and 'consume(++((p)))' in text and '(p) = next()' in text for text in out)


def test_prior_address_escape_prevents_staging_before_a_call():
    source = """void f(void) {
    void *p;
    remember(& /* address */ (p));
    use(mutate(), p);
}
"""
    assert variants(source, 'f') == []
