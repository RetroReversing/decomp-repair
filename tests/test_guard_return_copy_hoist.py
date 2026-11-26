"""A plain copy written just after an early-return guard, moved above the guard."""
from decomprepair import guard_return_copy_hoist as p
from decomprepair import registry

SOURCE = '''typedef int s32;
s32 next(void);
void done(s32, s32);
s32 warn(void);

s32 draw(s32 *o)
{
    s32 idx;
    s32 w;
    idx = next();
    if (idx == -1) {
        warn();
        return 1;
    }
    w = idx;
    idx += 4;
    done(idx - w, o[0]);
    return 1;
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'draw')]


def test_the_copy_moves_above_its_guard():
    """The billboard drawer's step (with the call split, 250 -> 10 -> 0): `w = idx;` before `if (idx == -1)`."""
    [text] = texts(SOURCE)
    assert '    idx = next();\n    w = idx;\n    if (idx == -1) {\n        warn();\n        return 1;\n    }\n    idx += 4;' in text
    assert text.count('w = idx;') == 1


def test_a_cast_copy_is_taken():
    [text] = texts(SOURCE.replace('w = idx;', 'w = (s32) idx;'))
    assert '    w = (s32) idx;\n    if (idx == -1) {' in text


def test_a_guard_or_arm_that_names_the_local_is_left_alone():
    assert texts(SOURCE.replace('idx == -1', 'w == -1')) == []
    assert texts(SOURCE.replace('warn();', 'warn(); w = 2;')) == []


def test_an_arm_that_does_not_return_or_an_else_is_left_alone():
    assert texts(SOURCE.replace('        return 1;\n    }\n    w', '        idx = 0;\n    }\n    w')) == []
    assert texts(SOURCE.replace('        return 1;\n    }\n    w', '        return 1;\n    } else { idx = 2; }\n    w')) == []


def test_a_copy_of_memory_or_a_call_is_left_alone():
    assert texts(SOURCE.replace('w = idx;', 'w = o[1];')) == []
    assert texts(SOURCE.replace('w = idx;', 'w = next();')) == []


def test_it_declares_itself_to_the_registry():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'guard_return_copy_hoist')) == []
