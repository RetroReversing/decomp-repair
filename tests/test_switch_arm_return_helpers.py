"""Returning switch arms written as one `static inline` helper each.

Synthetic shape of a message dispatcher (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): on the real 150-instruction
function the plain `switch` scored 3986 and the helpers 0."""
from decomprepair import registry
from decomprepair import switch_arm_return_helpers as m

SOURCE = '''typedef struct { short kind; void *queue; void *data; } Msg;
extern char gQueue[];
extern int gLocked;

int dispatch(Msg *msg) {
    void *pad;

    switch (msg->kind) {
    case 1: {
        char *q;
        if (gLocked != 0) {
            return 1;
        }
        q = gQueue;
        receive(q, 0);
        send(q, 0);
        return 0;
    }
    case 2:
        pad = msg->data;
        start(gQueue);
        read(pad);
        return 1;
    case 3:
        break;
    }
    return 0;
}
'''


def test_all_arms_then_each_alone():
    results = m.variants(SOURCE, 'dispatch')
    assert [family for family, _ in results] == [m.FAMILY] * 3
    text = results[0][1]
    assert 'static inline int dispatch_case_1(void)\n{\n  char *q;' in text
    assert 'static inline int dispatch_case_2(Msg *msg)\n{\n  void *pad;\n  pad = msg->data;' in text
    assert 'case 1: return dispatch_case_1();' in text
    assert 'case 2: return dispatch_case_2(msg);' in text
    assert 'case 3:\n        break;' in text
    assert text.count('void *pad;') == 1  # the helper's local: the function's own is gone
    single = results[1][1]
    assert 'dispatch_case_2' not in single and '    void *pad;\n\n    switch' in single


def test_void_function_calls_then_returns():
    source = 'void f(int a) {\n    switch (a) {\n    case 0:\n        g(a);\n        return;\n    }\n}\n'
    (_, text), = m.variants(source, 'f')
    assert 'static inline void f_case_0(int a)' in text
    assert 'case 0: f_case_0(a);\n      return;' in text


def test_a_local_the_arm_reads_or_lends_stays():
    reads = ('int f(int a) {\n    int x;\n    x = a;\n    switch (a) {\n    case 0:\n        g(x);\n        return 1;\n'
             '    }\n    return 0;\n}\n')
    assert m.variants(reads, 'f') == []
    lent = ('int f(int a) {\n    int x;\n    h(&x);\n    switch (a) {\n    case 0:\n        x = 2;\n        g(x);\n'
            '        return 1;\n    }\n    return 0;\n}\n')
    assert m.variants(lent, 'f') == []


def test_arms_that_break_or_call_nothing_stay():
    source = ('int f(int a) {\n    switch (a) {\n    case 0:\n        g(a);\n        break;\n    case 1:\n'
              '        return 2;\n    }\n    return 0;\n}\n')
    assert m.variants(source, 'f') == []


def test_declared_in_the_registry():
    assert any(repair.module == 'switch_arm_return_helpers' for repair in registry.declared())
