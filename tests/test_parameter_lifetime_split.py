from decomprepair import integer_lifetime_repairs

SOURCE = '''
void example(s32 argument) {
    s32 value;
    if (!ready) {
        call(argument & 0xff);
    }
    argument = source_value;
    value = argument;
    sink = value;
}
'''


def candidates(source):
    return [text for family, text in integer_lifetime_repairs.variants(source, 'example')
            if family == 'split_integer_lifetime']


def test_split_reassigned_parameter_after_its_incoming_use():
    result = candidates(SOURCE)
    assert len(result) == 1
    assert 'call(argument & 0xff);' in result[0]
    assert 's32 __repair_argument_local;' in result[0]
    assert '__repair_argument_local = source_value;' in result[0]
    assert 'value = __repair_argument_local;' in result[0]


def test_preserve_ambiguous_or_dependent_parameter_lifetimes():
    cases = [
        SOURCE.replace('argument = source_value;', 'argument = argument + source_value;'),
        SOURCE.replace('call(argument & 0xff);', 'call(&argument);'),
        SOURCE.replace('argument = source_value;', 'if (ready) argument = source_value;'),
        SOURCE.replace('argument = source_value;', 'argument = source_value;\n    call(argument);'),
        SOURCE.replace('argument = source_value;', 'while (ready) argument = source_value;'),
        SOURCE.replace('    s32 value;', '    s32 value;\n    s32 argument;'),
        SOURCE.replace('    s32 value;', '    s32 value, argument;'),
        '#define call(x) #x\n' + SOURCE,
    ]
    for source in cases:
        assert not candidates(source)


def test_known_header_macros_are_not_rewritten():
    assert not integer_lifetime_repairs.parameter_split_variants(SOURCE, 'example', '#define call(x) #x')
