from decomprepair.cursor_lockstep_fold import FAMILY, variants

LOCKSTEP = '''
static int back(void)
{
    return -1;
}

static u8 *plus_two(u8 *x)
{
    return x + 2;
}

void f(u8 *out, u8 *p, u8 *table, s32 n, s32 mode)
{
    u8 *q;
    s32 i;
    i = 0;
    q = plus_two(out);
    do {
        switch (mode) {
        case 0:
            out[0] = table[p[0]];
            q[back()] = table[p[1]];
            out += 3;
            q[0] = table[p[2]];
            q += 3;
            break;
        default:
            out[0] = p[0];
            q[-1] = p[1];
            out += 3;
            q[0] = p[2];
            q += 3;
            break;
        }
        p += 3;
        i += 1;
    } while (i < n);
}
'''

COUNTER = '''
void g(u8 *p, u8 *table, s32 n)
{
    u8 *q;
    s32 i;
    i = 0;
    q = p + 2;
    do {
        use(table[q[(s32) (i * 3) - 1]], table[q[i * 3]], p[0]);
        p += 3;
        i += 1;
    } while (i < n);
}
'''


def folded(source, name):
    return [text for family, text in variants(source, name) if family == FAMILY]


def test_a_cursor_stepped_beside_its_pointer_becomes_offsets_from_the_pointer():
    text = folded(LOCKSTEP, 'f')[0]
    assert 'u8 *q;' not in text and 'q = plus_two' not in text and 'q[' not in text and 'q +=' not in text
    # the base's own step moves to where the cursor's was, and the offsets are the cursor's plus its distance
    assert 'out[0] = table[p[0]];\n            out[1] = table[p[1]];\n            out[2] = table[p[2]];\n            out += 3;' in text
    assert 'out[1] = p[1];\n            out[2] = p[2];\n            out += 3;' in text


def test_a_read_of_the_base_after_its_old_step_sees_the_advanced_pointer():
    source = LOCKSTEP.replace('            q[0] = table[p[2]];\n            q += 3;\n            break;\n        default',
                              '            use(out[0]);\n            q[0] = table[p[2]];\n            q += 3;\n            break;\n        default', 1)
    text = folded(source, 'f')[0]
    # `out += 3` was before `use(out[0])`: with the step moved below it, the read is three elements on
    assert 'use(out[3]);' in text
    assert 'out += 3;\n            break' in text


def test_a_loop_counter_in_the_index_is_the_pointer_step():
    text = folded(COUNTER, 'g')[0]
    assert 'use(table[p[1]], table[p[2]], p[0]);' in text
    assert 'u8 *q;' not in text and 'q = p + 2;' not in text


def test_a_step_that_does_not_pair_with_the_base_stays():
    assert not folded(LOCKSTEP.replace('            out += 3;\n            q[0] = table[p[2]];', '            q[0] = table[p[2]];'), 'f')


def test_a_cursor_used_as_a_pointer_stays():
    assert not folded(COUNTER.replace('use(table[q[(s32) (i * 3) - 1]]', 'use(q, table[q[(s32) (i * 3) - 1]]'), 'g')


def test_a_counter_with_another_stride_stays():
    assert not folded(COUNTER.replace('p += 3;', 'p += 4;'), 'g')


def test_a_loop_that_can_leave_early_stays():
    assert not folded(COUNTER.replace('p += 3;', 'if (n == 7) { return; }\n        p += 3;'), 'g')
