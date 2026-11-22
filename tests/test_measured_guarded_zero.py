from decomprepair.measured_guarded_zero import variants

SOURCE = '''void run(void) {
    s32 count;
    void *cursor;
    count = 0;
    if (ready(&state) != 0) {
        cursor = records;
        do {
            count += 1;
            visit(cursor);
            cursor += 4;
        } while (count == 0);
    }
}'''
T = ['jal ready', 'sw $s0, 16($sp)', 'beqz $v0, 96', 'move $s1, $zero']
C = ['move $s1, $zero', 'jal ready', 'sw $s0, 16($sp)', 'beqz $v0, 100', 'nop']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(max(len(T), len(C)))]


def test_moves_unescaped_local_after_call_guard():
    label, fixed = variants(SOURCE, 'run', '', ROWS)[0]
    assert label == 'measured_guarded_zero'
    assert fixed.index('if (ready(&state) != 0)') < fixed.index('count = 0;') < fixed.index('cursor = records;')
    assert fixed.count('count = 0;') == 1


def test_rejects_observable_or_ambiguous_initialization():
    assert not variants(SOURCE, 'run', '', [(' ', x, x) for x in T])
    assert not variants(SOURCE.replace('if (ready(&state)', 'if (ready(&count)'), 'run', '', ROWS)
    assert not variants(SOURCE.replace('visit(cursor);', 'visit(&count);'), 'run', '', ROWS)
    assert not variants(SOURCE.replace('\n}', '\n    use(count);\n}'), 'run', '', ROWS)
    assert not variants(SOURCE.replace('s32 count;', 'volatile s32 count;'), 'run', '', ROWS)
    assert not variants(SOURCE, 'run', '#define count global_count', ROWS)
