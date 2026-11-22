from decomprepair.guard_temp_sink_repairs import FAMILY, variants

SOURCE = '''
int f(int input) {
    int sum;
    sum = (unsigned char)input + 16;
    if (input != 255) {
        int result = input;
        if (sum >= 0) {
            result += 16;
            if (sum >= 256) result = 255;
        } else {
            result = 0;
        }
        return result;
    }
    return 0;
}
'''


def test_attached_brace_sinks_after_initialized_declaration():
    [(family, candidate)] = variants(SOURCE, 'f')
    assert family == FAMILY
    assert 'int result = input;\n        sum = (unsigned char)input + 16;' in candidate
    assert candidate.count('sum = (unsigned char)input + 16;') == 1


def test_does_not_cross_a_declaration_using_the_temp():
    source = SOURCE.replace('int result = input;', 'int result = sum;')
    assert not variants(source, 'f')


def test_does_not_cross_an_unknown_declaration_initializer():
    source = SOURCE.replace('int result = input;', 'float result = get();')
    assert not variants(source, 'f')


def test_does_not_cross_a_declaration_shadowing_an_operand():
    source = SOURCE.replace('int result = input;', 'int input = 2;')
    assert not variants(source, 'f')
