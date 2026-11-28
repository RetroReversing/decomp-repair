import shutil
import subprocess

import pytest

from decomprepair.pointer_value_split import FAMILY, variants

SOURCE = """struct V { int field; int other; };
struct E { void *value; };
void observe(void *);
void f(struct V *v, struct E *e) {
    void *p;
    do { p = &v->field; } while (0);
    observe(p);
    e->value = p;
}
"""


def test_offers_value_copies_for_a_stable_pointer_and_keeps_the_store():
    out = variants(SOURCE, 'f')
    assert len(out) == 3
    assert all(family == FAMILY and 'void *__split_p;' in text for family, text in out)
    assert all('e->value = __split_p;' in text and 'observe(p);' in text for _, text in out)
    assert any('do { __split_p = p; } while (0);' in text for _, text in out)


def test_copy_preserves_the_pointer_seen_by_the_callback_and_the_event(tmp_path):
    cc = shutil.which('cc')
    if not cc:
        pytest.skip('a C compiler is not installed')
    harness = """
void *observed;
void observe(void *value) { observed = value; }
int main(void) {
    struct V v = { 7, 9 };
    struct E e = { 0 };
    f(&v, &e);
    return observed != &v.field || e.value != &v.field;
}
"""
    for index, (_, text) in enumerate(variants(SOURCE, 'f')):
        src = tmp_path / f'candidate{index}.c'
        exe = tmp_path / f'candidate{index}'
        src.write_text(text + harness)
        subprocess.run([cc, '-std=c99', str(src), '-o', str(exe)], check=True, timeout=20, capture_output=True)
        subprocess.run([str(exe)], check=True, timeout=20, capture_output=True)


@pytest.mark.parametrize('statement', [
    'observe(&p);',
    'observe(&(p));',
    'p = &v->other;',
    '(p) = &v->other;',
    'p += 1;',
    'p++;',
    '++(p);',
    'struct V *p;',
    'goto end;',
    '__asm("nop");',
    '__builtin_longjmp(x, 1);',
    'void nested(void) { p = &v->other; }',
])
def test_does_not_copy_a_pointer_that_can_change_or_escape(statement):
    source = SOURCE.replace('    observe(p);', '    ' + statement + '\n    observe(p);')
    assert variants(source, 'f') == []


@pytest.mark.parametrize('header,statement', [
    ('#define MUTATE p = &v->other', 'MUTATE;'),
    ('#define MUTATE() (p = &v->other)', 'MUTATE();'),
])
def test_macros_cannot_hide_a_pointer_update(header, statement):
    source = SOURCE.replace('    observe(p);', '    ' + statement + '\n    observe(p);')
    assert variants(source, 'f', header) == []


def test_does_not_capture_from_an_unbraced_arm_or_cross_a_block():
    assert variants(SOURCE.replace('    do { p = &v->field; } while (0);',
                                   '    if (v) do { p = &v->field; } while (0);'), 'f') == []
    assert variants(SOURCE.replace('    e->value = p;', '    if (v) { e->value = p; }'), 'f') == []


def test_does_not_shadow_an_existing_scratch_name():
    source = SOURCE.replace('    void *p;', '    void *p;\n    void *__split_p;')
    assert variants(source, 'f') == []


def test_unknown_includes_and_command_line_macros_are_not_assumed_safe():
    assert variants(SOURCE, 'f', '#include "private.h"') == []
    assert variants(SOURCE, 'f', flags=['-DCHANGE_P=1']) == []


def test_grouped_declarations_cannot_hide_a_shadowed_pointer():
    source = SOURCE.replace('    observe(p);', '    { void *other, *p; p = &v->other; observe(other); }')
    assert variants(source, 'f') == []


def test_macro_before_capture_cannot_hide_an_address_escape():
    header = '#define REMEMBER() save(&p)'
    source = SOURCE.replace('    do { p = &v->field; } while (0);',
                            '    REMEMBER();\n    do { p = &v->field; } while (0);')
    assert variants(source, 'f', header) == []


def test_cpp_reference_parameters_and_aliases_are_not_assumed_safe():
    source = SOURCE.replace('    observe(p);', '    mutate(p);')
    assert variants(source, 'f', 'void mutate(void *&value);') == []
    assert variants(SOURCE, 'f', flags=['-x', 'c++']) == []
    assert variants(SOURCE, 'f', 'struct X { void operator=(void *); };') == []
    source = SOURCE.replace('    observe(p);', '    auto &alias = p;\n    mutate(alias);')
    assert variants(source, 'f') == []
