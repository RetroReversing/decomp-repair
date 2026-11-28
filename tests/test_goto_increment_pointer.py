from decomprepair.goto_increment_pointer import variants

SOURCE = '''
typedef signed int s32;
extern char table[];
void f(int i) {
    s32 value;
    s32 *ptr;
    if (i) {
        ptr = (i * 4) + table;
        *ptr = *ptr + 1;
        goto done;
    }
    value = 0;
store:
    *ptr = value;
done:
    use();
}
'''


def test_stages_real_pointer_before_shared_store():
    children = variants(SOURCE, 'f')
    assert len(children) == 2
    text = children[0][1]
    assert '__repair_increment_ptr = (i * 4) + table;' in text
    assert 'value = *__repair_increment_ptr + 1;' in text
    assert 'ptr = __repair_increment_ptr;' in text
    assert 'goto store;' in text
    staged = children[1][1]
    assert '__repair_increment_value = *__repair_increment_ptr + 1;' in staged
    assert 'ptr = __repair_increment_ptr;\n        value = __repair_increment_value;' in staged


def test_rejects_later_read_backedge_escape_shadow_and_unbraced_control():
    cases = (
        SOURCE.replace('use();', 'use(value);'),
        SOURCE.replace('use();', 'if (i) goto store;'),
        SOURCE.replace('use();', 'use(&value);'),
        SOURCE.replace('use();', 'use(&ptr);'),
        SOURCE.replace('        ptr =', '        if (i)\n        ptr ='),
        SOURCE.replace('    s32 value;', '    s32 value;\n    { int x, value; use(value); }'),
        SOURCE.replace('extern char table[];', 'extern volatile char table[];'),
        SOURCE + '\nint line = __LINE__;\n',
        SOURCE + '\nclass C {};\n',
    )
    for source in cases:
        assert variants(source, 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define ptr other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []


def test_stages_both_real_increment_paths_together():
    source = SOURCE.replace('extern char table[];', 'extern char table[];\nextern char other[];')
    source = source.replace('    value = 0;', """    { __typeof__(other + 0) base; base = other; ptr = base + (i * 4); }
    value = *ptr + 1;
    goto store;
    value = 0;""")
    children = variants(source, 'f')
    assert len(children) == 3
    text = children[2][1]
    assert '__repair_increment_base = table;' in text
    assert '__repair_second_ptr = base + (i * 4);' in text
    assert '__repair_second_value = *__repair_second_ptr + 1;' in text
    assert 'ptr = __repair_second_ptr;' in text
    assert 'value = __repair_second_value;' in text
    # Delaying a pointer write must not change the index it reads.
    assert len(variants(source.replace('(i * 4); }', '(ptr * 4); }'), 'f')) == 2
    assert len(variants(source.replace('{ __typeof__(other', 'if (i) { __typeof__(other'), 'f')) == 2
