"""A loop's `if (c) { step; continue; } rest; step;` written as `if (!c) { rest; } step;`."""
import re

from decomprepair.continue_step_guard import FAMILY, variants

CODE = '''extern int gMode;
extern void work(int);
void run(int n)
{
    int i = 0;
    while (i < n) {
        if (gMode == 7 && i == 1) {
            i++;
            continue;
        }
        work(i);
        work(i + 1);
        i++;
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_skip_becomes_a_guard_around_the_rest():
    children = variants(CODE, 'run')
    assert [family for family, _ in children] == [FAMILY]
    text = squash(children[0][1])
    assert 'while (i < n) { if (!(gMode == 7 && i == 1)) { work(i); work(i + 1); } i++; } }' in text
    assert 'continue' not in text


def test_an_equality_is_flipped_and_an_ordering_is_negated():
    equal = variants(CODE.replace('gMode == 7 && i == 1', 'gMode == 7'), 'run')[0][1]
    assert 'if (gMode != 7) {' in equal
    ordered = variants(CODE.replace('gMode == 7 && i == 1', 'gMode < 7'), 'run')[0][1]
    assert 'if (!(gMode < 7)) {' in ordered  # `>=` would differ for a NaN


def test_a_bare_continue_guards_the_whole_rest():
    code = CODE.replace('{\n            i++;\n            continue;\n        }', 'continue;')
    text = squash(variants(code, 'run')[0][1])
    assert 'if (!(gMode == 7 && i == 1)) { work(i); work(i + 1); i++; } } }' in text


def test_other_shapes_are_left_alone():
    # another step in the skip than at the foot
    assert variants(CODE.replace('i++;\n            continue', 'i += 2;\n            continue'), 'run') == []
    # nothing steps at the foot
    assert variants(CODE.replace('        i++;\n    }\n}', '    }\n}'), 'run') == []
    # the step at the foot is only the body of another `if`
    assert variants(CODE.replace('work(i + 1);\n        i++;', 'if (gMode)\n        i++;'), 'run') == []
    # an `else` belongs to the skip
    assert variants(CODE.replace('continue;\n        }', 'continue;\n        } else {\n            work(2);\n        }'), 'run') == []
    # the rest declares a name the step uses
    assert variants(CODE.replace('work(i);', 'int i = 3;\n        work(i);'), 'run') == []
    # a `continue` with nothing after it has nothing to guard
    assert variants('void run(int n)\n{\n    while (n) {\n        n--;\n        if (n) {\n            continue;\n        }\n    }\n}\n', 'run') == []
    assert variants(CODE, 'missing') == []
