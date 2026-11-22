from decomprepair import loop_limit_reassign_repairs as repair

# m2c's offset form: the cursor walks 8-byte records and the test subtracts the base
OFFSET = '''void f(void *list, s32 count)
{
    void *cursor;
    s32 total;
    total = 0;
    cursor = list;
    if (count != 0)
    {
        do
        {
            total += *((s32 *) cursor);
            cursor += 8;
        }
        while ((((u32) cursor) - ((u32) list)) < ((2 * (2 * ((u32) count))) * 2));
    }
}
'''


def test_offset_form_becomes_a_pointer_bound_with_a_second_set():
    found = repair.variants(OFFSET, 'f')
    assert [family for family, _ in found] == ['loop_limit_reassign']
    text = found[0][1]
    assert 'u32 __repair_loop_limit;' in text
    assert '__repair_loop_limit = 0;\n        do' in text
    assert ('while (__repair_loop_limit = ((2 * (2 * ((u32) count))) * 2) + (u32) list, '
            '(u32) cursor < __repair_loop_limit);') in text


def test_pointer_bound_keeps_its_relation():
    source = '''void f(char *p, s32 n)
{
    do { *p = 0; p += 1; } while ((u32) p <= (u32) (n * 4 + 8));
}
'''
    text = repair.variants(source, 'f')[0][1]
    assert 'while (__repair_loop_limit = (u32) (n * 4 + 8), (u32) p <= __repair_loop_limit);' in text


def test_a_limit_the_loop_changes_or_reads_through_memory_is_left_alone():
    changes = 'void f(char *p, s32 n) { do { n += 1; p += 1; } while ((u32) p < (u32) (n * 4)); }'
    memory = 'void f(char *p, s32 *n) { do { p += 1; } while ((u32) p < (u32) (n[0] * 4)); }'
    call = 'void f(char *p, s32 n) { do { p += 1; } while ((u32) p < (u32) (g(n) * 4)); }'
    constant = 'void f(char *p) { do { p += 1; } while ((u32) p < 0x80); }'
    for source in (changes, memory, call, constant):
        assert not repair.variants(source, 'f')


def test_each_loop_gets_its_own_local_and_both_together():
    source = '''void f(char *p, char *q, s32 n)
{
    do { *p = 0; p += 1; } while ((u32) p < (u32) (n * 4));
    do { *q = 0; q += 1; } while ((u32) q < (u32) (n * 8));
}
'''
    found = [text for _, text in repair.variants(source, 'f')]
    assert len(found) == 3
    assert 'u32 __repair_loop_limit_0; u32 __repair_loop_limit_1;' in found[2]
    assert found[0].count('__repair_loop_limit = ') == 2
