"""An `if (0)` debug block guarded by a local flag set to zero, so the compiler keeps the test."""
from decomprepair import registry
from decomprepair import zero_guard_local as p

SOURCE = '''void say(char *);
extern unsigned char *CMDS;

int run(int n)
{
    unsigned char *cmd;

    cmd = CMDS;
    for (;;) {
        switch (*cmd) {
        case 0:
            if (0) {
                say("MTXLOAD\\n");
            }
            cmd += 3;
            break;
        default:
            return n;
        }
    }
}
'''


def test_the_dead_block_reads_a_zero_flag():
    """The 618-instruction display-list interpreter (SN64 GCC 2.8.1): 9751 -> 9166 with the block kept."""
    [(family, text)] = p.variants(SOURCE, 'run')
    assert family == 'zero_guard_local'
    assert '{\n    int debug = 0;\n    unsigned char *cmd;\n' in text
    assert 'if (debug) {\n                say(' in text
    assert 'if (0)' not in text


def test_a_taken_name_gets_another_and_every_test_is_rewritten():
    source = SOURCE.replace('int run(int n)', 'int debug;\nint run(int n)').replace(
        '            cmd += 3;\n', '            if (0 != 0) {\n                say("X");\n            }\n            cmd += 3;\n')
    [(_, text)] = p.variants(source, 'run')
    assert 'int debug2 = 0;' in text and text.count('if (debug2)') == 2


def test_no_dead_test_no_child():
    assert p.variants(SOURCE.replace('if (0)', 'if (n)'), 'run') == []


def test_it_is_declared():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'zero_guard_local')) == []
