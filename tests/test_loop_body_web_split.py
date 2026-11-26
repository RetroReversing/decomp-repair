"""loop_body_web_split: a loop body's reused pointer and constant holder split by web, alone and together.

Synthetic shape of an SN64 GCC 2.8.1 vertex builder (544 instructions): one `v` served three vertex records and the
vertex count `nv` also held the alpha constants inside the loop. Each split alone was worse (1350 -> 1395, -> 1930);
both together (1955) let store_constant_web, statement_slide and dead_scratch_reuse reach 530."""
from decomprepair import loop_body_web_split as s

SOURCE = '''s32 f(s32 count, s32 base) {
    s32 m[3][3];
    s32 i;
    s32 k;
    s32 nv;

    for (i = k = 0; i < count; i++) {
        Vtx *v = &T[k++ + base];
        v->ob[0] = A[i].x;
        v->cn[0] = 0xFF;
        v = &T[k++ + base];
        v->ob[0] = A[i].y;
        nv = 0x80;
        v->cn[3] = nv;
        v = &T[k++ + base];
        v->ob[0] = A[i].z;
        nv = 0;
        v->cn[3] = nv;
    }
    nv = k;
    use(m, nv);
    return nv;
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'f') if family == s.FAMILY]


def test_three_children_pointer_holder_and_both():
    pointer, holder, both = _texts()
    assert '        Vtx *v = &T[k++ + base];\n        Vtx *v2;\n        Vtx *v3;\n' in pointer
    assert 'v2 = &T[k++ + base];\n        v2->ob[0] = A[i].y;' in pointer
    assert 'v3 = &T[k++ + base];\n        v3->ob[0] = A[i].z;' in pointer
    assert 'v->cn[0] = 0xFF;' in pointer and 'nv = 0x80;' in pointer
    assert '    for (i = k = 0; i < count; i++) {\n        s32 nv2;\n' in holder
    assert 'nv2 = 0x80;\n        v->cn[3] = nv2;' in holder and 'nv2 = 0;\n        v->cn[3] = nv2;' in holder
    assert '    nv = k;\n    use(m, nv);\n    return nv;' in holder
    assert 'nv2 = 0x80;\n        v2->cn[3] = nv2;' in both and 'nv2 = 0;\n        v3->cn[3] = nv2;' in both


def test_a_name_the_text_already_uses_gets_an_underscore():
    source = '#define Q(v2) (v2)\n' + SOURCE
    pointer = _texts(source)[0]
    assert 'Vtx *v_2;' in pointer and 'v_2->ob[0] = A[i].y;' in pointer


def test_a_holder_read_after_the_loop_is_left_alone():
    source = SOURCE.replace('    nv = k;\n    use(m, nv);', '    use(m, nv);')
    texts = _texts(source)
    assert len(texts) == 1 and 'nv2' not in texts[0]


def test_a_holder_read_before_its_first_load_is_left_alone():
    source = SOURCE.replace('        v->cn[0] = 0xFF;\n', '        v->cn[0] = nv;\n')
    assert all('nv2' not in text for text in _texts(source))


def test_a_holder_named_in_the_loop_header_is_left_alone():
    source = SOURCE.replace('i < count;', 'i < count + nv;')
    assert all('nv2' not in text for text in _texts(source))


def test_a_conditional_reassignment_stops_the_pointer_split():
    source = SOURCE.replace('        v = &T[k++ + base];\n        v->ob[0] = A[i].z;',
                            '        if (k) {\n            v = &T[k];\n        }\n        v->ob[0] = A[i].z;')
    assert all('Vtx *v2' not in text for text in _texts(source))


def test_a_reassignment_reading_the_pointer_stops_the_split():
    source = SOURCE.replace('        v = &T[k++ + base];\n        v->ob[0] = A[i].z;', '        v = v + 1;\n        v->ob[0] = A[i].z;')
    assert all('Vtx *v3' not in text for text in _texts(source))


def test_no_loop_no_children():
    source = SOURCE.replace('    for (i = k = 0; i < count; i++) {', '    if (count) {')
    assert _texts(source) == []


def test_a_goto_stops_the_rewrite():
    source = SOURCE.replace('    nv = k;\n', '    goto out;\nout:\n    nv = k;\n')
    assert _texts(source) == []
