from decomprepair import registry
from decomprepair.typeof_goto_web_split import variants

SOURCE = '''
extern unsigned char table[];
void f(int c) {
    __typeof__(*table + 0) index;
    if (c) {
        index = table[0];
        use(index);
        goto done;
    }
    index = table[1];
    use(index);
done:
    finish();
}
'''


def test_splits_distinct_goto_webs_with_the_exact_promoted_type():
    result = variants(SOURCE, 'f')
    assert len(result) == 1
    text = result[0][1]
    assert '__typeof__(*table + 0) index_w1;' in text
    assert 'index_w1 = table[1];' in text
    assert 'use(index_w1);' in text
    assert any(entry.module.endswith('typeof_goto_web_split') for entry in registry.declared())


def test_keeps_reaching_values_and_escapes_together():
    assert variants(SOURCE.replace('    use(index);\ndone:', 'done:\n    use(index);'), 'f') == []
    assert variants(SOURCE.replace('    finish();', '    use(&index);'), 'f') == []
    assert variants(SOURCE.replace('        use(index);', '        if (c) goto done;\n        use(index);').replace('    finish();', '    use(index);'), 'f') == []


def test_declines_unknown_preprocessor_or_qualified_inputs():
    assert variants(SOURCE, 'f', header='#include "unknown.h"') == []
    assert variants(SOURCE, 'f', flags=['-DX=1']) == []
    assert variants(SOURCE.replace('extern unsigned char table[];', 'extern volatile unsigned char table[];'), 'f') == []
    assert variants(SOURCE, 'f', header='#define index other') == []
    assert variants(SOURCE + '\nint n = __LINE__;', 'f') == []
    assert variants(SOURCE.replace('        index = table[0];', '        { int*index = 0; use(index); }\n        index = table[0];'), 'f') == []
    assert variants(SOURCE.replace('        index = table[0];', '        { __typeof__(*table + 0) index = 0; use(index); }\n        index = table[0];'), 'f') == []
    assert variants(SOURCE.replace('        index = table[0];', '        { int index = 0; use(index); }\n        index = table[0];'), 'f') == []
