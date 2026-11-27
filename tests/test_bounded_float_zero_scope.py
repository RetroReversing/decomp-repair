from decomprepair.bounded_float_zero_scope import variants

SOURCE = '''
extern s8 input;
extern s32 output;
void f(void) {
    f32 pitch, pan;
    s32 old;
    if (flag) old = 2;
    pitch = input;
    if (pitch > 10.0f) {
        if (pitch > 60.0f) pitch = 60.0f;
        pitch -= 10.0f;
        sink();
    } else if (pitch < -10.0f) {
        if (pitch < -60.0f) pitch = -60.0f;
        pitch += 10.0f;
        sink();
    } else send(1.0f);
    pan = read_pan();
    use(pan);
    if (flag) output = 0;
}
'''
ASM = 'sdc1 $f20, 0x18($sp)\nsdc1 $f22, 0x20($sp)\n'


def test_offers_bounded_copy_and_if_scope_together():
    children = variants(SOURCE, 'f', ASM, ['-O1'])
    assert len(children) == 1
    child = children[0][1]
    assert 'do { if (pitch > 10.0f)' in child
    assert 'while (0);' in child
    assert 'old = (s32)pitch; output = old & ~old;' in child


def test_rejects_unbounded_or_observable_cases():
    assert variants(SOURCE, 'f', ASM, ['-O2']) == []
    assert variants(SOURCE, 'f', ASM.replace('$f22', '$f24'), ['-O1']) == []
    assert variants(SOURCE.replace('extern s8 input;', 'extern s32 input;'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE, 'f', ASM, ['-O1'], 'typedef long s8;') == []
    assert variants(SOURCE.replace('pitch -= 10.0f;', 'pitch *= 10.0f;'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE.replace('pitch -= 10.0f;', 'pitch = other;'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE.replace('pitch -= 10.0f;', 'pitch -= 10001.0f;'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE.replace('if (flag) output = 0;', 'if (flag) output = 0; use(old);'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE.replace('sink();', 'send(&pitch);'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE.replace('sink();', 'break;'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE.replace('pan = read_pan();', 'while (flag) pan = read_pan();'), 'f', ASM, ['-O1']) == []


def test_rejects_conditionally_uninitialized_float():
    assert variants(SOURCE.replace('    pitch = input;', '    if (flag) pitch = input;'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE.replace('    pitch = input;', '    if (flag)\n        pitch = input;'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE.replace('    pitch = input;', '    if (flag) { pitch = input; }'), 'f', ASM, ['-O1']) == []


def test_keeps_conditional_store_conditional():
    child = variants(SOURCE, 'f', ASM, ['-O1'])[0][1]
    assert 'if (flag) { old = (s32)pitch; output = old & ~old; }' in child


def test_ignores_commented_input_declarations():
    source = SOURCE.replace('extern s8 input;', '/* extern s8 input; */ extern s32 input;')
    assert variants(source, 'f', ASM, ['-O1']) == []


def test_rejects_macro_aliases_for_accessed_names():
    for name in ('input', 'output', 'pitch', 'old'):
        assert variants(SOURCE, 'f', ASM, ['-O1'], '#define ' + name + ' hidden') == []


def test_rejects_skipped_initialization_and_shadowed_input():
    assert variants(SOURCE.replace('    pitch = input;', '    switch (flag) { case 0: pitch = input; }'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE.replace('    f32 pitch, pan;', '    s32 input;\n    f32 pitch, pan;'), 'f', ASM, ['-O1']) == []
    assert variants(SOURCE, 'f', ASM, ['-O1'], '#define MUTATE() (pitch = 1e30f)') == []
