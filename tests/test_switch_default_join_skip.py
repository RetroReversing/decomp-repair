from decomprepair import registry
from decomprepair.switch_default_join_skip import FAMILIES, REPAIR, variants

SOURCE = """void tick(Voice *v) {
    s32 result;
    s32 e;
    do {
        switch (next(v)) {
            case 0x1:
                if (v->a) {
                    v->b = 1;
                } else {
                    case 0x0:
                    block_4:
                    goto release;
                }
                result = 0;
                break;
            case 0x2:
                work(v);
            default:
                result = 0;
                break;
            case 0x3:
                result = run(v);
                break;
            case 0x6:
                e = find(v);
                result = 0;
                if (e) {
                    v->c = e;
                } else {
                    goto block_4;
                }
                break;
        }
        goto complete;
        release:
        stop(v);
        result = 1;
        complete:
        if (result & 0xFF)
            break;
    } while (++v->n < 0x21);
}
"""


def flat(text):
    return ' '.join(text.split())


def test_all_three_edits_come_as_one_child():
    out = dict(variants(SOURCE, 'tick'))
    assert set(out) == set(FAMILIES)
    both = flat(out['switch_tail_into_arm_join_skip'])
    # The release code is in case 6's else, under `case 0x0:`; case 1's else goes there.
    assert flat('case 0x0:\n                  release:\n                  stop(v);\n                  result = 1;') in both
    assert 'block_4' not in both
    assert flat('} else {\n                  goto release;\n                }') in both
    # The default is last, sets the tested copy and skips the copy; case 2 keeps its `result = 0`.
    assert flat('default:\n              done = 0;\n              goto command_test;\n        }') in both
    assert flat('work(v);\n                result = 0;') in both
    assert flat('done = result;\n        command_test:\n        if (done & 0xFF)') in both
    assert flat('u8 result;\n    s32 done;') in both
    assert 'goto complete' not in both


def test_the_default_skip_alone_keeps_the_tail_and_the_type():
    out = dict(variants(SOURCE, 'tick'))
    alone = out['switch_default_join_skip']
    assert 's32 result;\n    s32 done;' in alone
    assert 'goto complete;\n        release:' in alone
    assert 'u8 result;' in out['switch_default_join_skip_narrow']


def test_no_child_without_a_tested_result_or_a_constant_default():
    assert variants(SOURCE.replace('if (result & 0xFF)', 'if (v->stop)'), 'tick') == []
    assert not [f for f, _ in variants(SOURCE.replace('default:\n                result = 0;',
                                                       'default:\n                result = v->k;'), 'tick')
                if 'join_skip' in f]


def test_declared():
    assert REPAIR['variants'] is variants
    repair = registry.get('switch_default_join_skip')
    assert repair is not None and not registry.problems(repair)
