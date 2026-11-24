from decomprepair import interpreter_arm_steps as m
from decomprepair import registry


def flat(text):
    return ' '.join(text.split())


def test_sum_accumulate_steps_writes_the_sum_in_one_variable():
    body = 'void f(void) {\n    v = (w >> 24 << 16) + (((s32) ((a - b) * c)) >> 7);\n}\n'
    out = m.sum_accumulate_steps(body)
    assert flat(out[0]) == flat('void f(void) {\n v = a - b;\n v = (v * c) >> 7;\n v += (w >> 24 << 16);\n}\n')


def test_arm_tail_share_drops_the_arms_own_tail():
    body = ('    case 1:\n        if (t) {\n            g(t);\n            r = 0;\n            break;\n        }\n'
            '        r = 0;\n        break;\n')
    assert flat(m.arm_tail_share(body)[0]) == flat('case 1: if (t) { g(t); } r = 0; break;')


def test_compare_into_arms_puts_the_compare_in_each_arm():
    helper = ('static s32 owns(u8 s, u8 b, u8 c) {\n    if (b == 0xFF)\n    {\n        x = s;\n        y = T[x];\n    }\n'
              '    else\n    {\n        x = R[b][c];\n        y = s;\n    }\n    if (y == x)\n    {\n        return 1;\n'
              '    }\n    return 0;\n}\n')
    out = [flat(x) for x in m.compare_into_arms(helper)]
    assert flat('if (b == 0xFF) { if (T[s] == s) { return 1; } } else { if (s == R[b][c]) { return 1; } }') in out[0]
    assert flat('else { if (R[b][c] == s) { return 1; } }') in out[1]


def test_operand_preload_temp_reads_the_global_into_the_next_local():
    body = '\n        lv = (p[0x2E]) + (*((u16 *) (&G)));\n        t = lv;\n'
    assert flat(m.operand_preload_temp(body)[0]) == flat('t = (*((u16 *) (&G))); lv = (p[0x2E]) + t; t = lv;')


def test_declared():
    repair = registry.get('interpreter_arm_steps')
    assert repair is not None and not registry.problems(repair)
