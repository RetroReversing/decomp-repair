"""A pointer just tested through, appended to a later call; and counters that lengthen a loop with no empty arm."""
from decomprepair import dead_narrow_counter, registry, tested_pointer_argument

SOURCE = '''void say(char *);
void load(char *, s32);

void f(void) {
    u16 i = 0;

    while (more(i) != 0) {
        if (*names[i] == ' ') {
            i++;
            continue;
        }
        if (quiet == 0) {
            say(path);
        }
        load(names[i], 0);
        i++;
    }
}
'''


def test_the_tested_pointer_is_appended_and_the_prototype_opened():
    out = [t for _, t in tested_pointer_argument.variants(SOURCE, 'f')]
    assert len(out) == 1  # `load` already takes it
    assert 'say(path, names[i]);' in out[0]
    assert 'void say();\nvoid load(char *, s32);' in out[0]


def test_float_prototypes_and_other_architectures_are_left_alone():
    assert tested_pointer_argument.variants(SOURCE.replace('void say(char *);', 'void say(f32);'), 'f') == []
    assert tested_pointer_argument.variants(SOURCE, 'f', arch='ppc') == []


def lengthened():
    return [t for fam, t in dead_narrow_counter.variants(SOURCE, 'f') if fam == dead_narrow_counter.LENGTH]


def test_a_loop_gets_a_counter_in_a_new_else_and_four_at_its_end():
    first = lengthened()[0]
    assert 'say(path);\n        } else {\n            dead_count_0++;\n        }\n' in first
    ends = ''.join(f'        dead_count_{k}++;\n' for k in range(1, 5))
    assert '        i++;\n' + ends + '    }\n}\n' in first
    assert all(f'    u8 dead_count_{k} = 0;\n' in first for k in range(5))


def test_counters_go_before_a_loops_last_jump():
    source = SOURCE.replace('        i++;\n    }\n}', '        i++;\n        continue;\n    }\n}')
    text = [t for fam, t in dead_narrow_counter.variants(source, 'f') if fam == dead_narrow_counter.LENGTH][0]
    assert 'dead_count_4++;\n        continue;\n    }' in text


def test_a_loop_without_calls_is_not_lengthened():
    assert dead_narrow_counter.variants('void f(void) {\n    for (;;) {\n        G++;\n    }\n}\n', 'f') == []


def test_both_declare_themselves():
    assert registry.get('tested_pointer_argument') is not None
    assert dead_narrow_counter.LENGTH in registry.get('dead_narrow_counter').families
