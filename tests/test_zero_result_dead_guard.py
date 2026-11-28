from decomprepair import zero_result_dead_guard as family

EARLY = """u16 f(Obj *obj, s32 *out, void **table, s32 *clip)
{
    u8 *model;
    u16 count;
    u32 i;

    model = table[*(u16 *) ((u8 *) obj + 8)];
    if (model == NULL) {
        return 0;
    }
    count = 0;
    i = 0;
    for (;;) {
        if (i >= 4) break;
        if (clip != NULL) {
            out[count++] = model[i];
        }
        i++;
    }
    return count;
}
"""
WRAPPED = EARLY.replace('''    if (model == NULL) {
        return 0;
    }
''', '''    if (model != NULL) {
''').replace('    return count;\n}', '    return count;\n    }\n    return 0;\n}')


def _children(source):
    return family.variants(source, 'f')


def test_both_spellings_give_the_combined_child():
    for source in (EARLY, WRAPPED):
        child = next(c for name, c in _children(source) if name == family.CHAIN)
        assert child.startswith('u32 f(')
        assert 'u32 __repair_result;' in child
        assert ('__repair_result = *(u16 *) ((u8 *) obj + 8);\n'
                '    __repair_result = __repair_result * 4 + (u32) table;\n'
                '    model = *(u8 * *) __repair_result;\n'
                '    if (model == NULL) { i = 1; }\n'
                '    __repair_result = 0;\n'
                '    if (model != NULL) {\n'
                '        if (clip != NULL) { i = 1; }\n') in child
        assert '__repair_result = count;\n    }\n    return __repair_result;\n}' in child
        assert 'return 0' not in child and child.count('{') == child.count('}')


def test_plain_child_has_no_dead_store():
    name, child = _children(EARLY)[0]
    assert name == family.PLAIN
    assert 'i = 1' not in child and '__repair_result = 0;\n    if (model != NULL) {' in child


def test_not_offered_without_the_shape():
    assert _children(EARLY.replace('return 0;', 'return 1;')) == []
    assert _children(EARLY.replace('        i++;', '        i++;\n        if (i) return 2;')) == []
    assert _children(EARLY.replace('u16 f(', 'void f(')) == []
