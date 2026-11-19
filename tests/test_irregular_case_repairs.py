from decomprepair import irregular_case_repairs as r

DRAFT = '''void f(int x) {
    switch (x) {
    case 0:                                     /* irregular */
        break;
    case 0x38:
        g(1);
        break;
    case 0x39:
        g(2);
        break;
    }
}
'''


def test_drops_an_empty_case():
    out = [t for _, t in r.variants(DRAFT, 'f')]
    assert out and 'case 0:' not in out[0] and 'case 0x38:' in out[0] and 'irregular' not in out[0]


def test_keeps_cases_when_the_switch_has_a_default():
    src = DRAFT.replace('    }\n}', '    default:\n        g(3);\n    }\n}')
    assert r.variants(src, 'f') == []


def test_keeps_a_case_that_another_falls_into():
    src = DRAFT.replace('        g(1);\n        break;\n    case 0x39:', '        g(1);\n    case 7:\n        break;\n    case 0x39:')
    assert all('case 7:' in t for _, t in r.variants(src, 'f'))


def test_never_touches_a_case_with_a_body():
    src = DRAFT.replace('    case 0:                                     /* irregular */\n        break;\n', '')
    assert r.variants(src, 'f') == []
