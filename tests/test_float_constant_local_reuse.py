from decomprepair.float_constant_local_reuse import variants

SOURCE = '''
void f(void) {
    f32 pitch, pan;
    pitch = get_pitch();
    if (pitch > 10.0f) {
        pitch -= 10.0f;
        send(pitch);
    }
    pan = get_pan();
    send(pan);
}
'''


def test_reuses_later_float_local_for_constant():
    children = variants(SOURCE, 'f', ['-O1'])
    assert any('pan = 10.0f; pitch -= pan;' in source for _, source in children)


def test_rejects_live_or_address_taken_local_and_other_profiles():
    assert variants(SOURCE, 'f', ['-O2']) == []
    assert variants(SOURCE.replace('pitch = get_pitch();', 'pan = get_pan(); pitch = get_pitch();'), 'f', ['-O1']) == []
    assert variants(SOURCE.replace('send(pitch);', 'send(pitch); use(&pan);'), 'f', ['-O1']) == []
    assert variants(SOURCE.replace('pan = get_pan();', 'pan = pan + 1.0f;'), 'f', ['-O1']) == []
    assert variants(SOURCE.replace('pitch -= 10.0f;', 'goto end; pitch -= 10.0f;'), 'f', ['-O1']) == []
