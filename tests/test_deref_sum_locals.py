from decomprepair.deref_sum_locals import FAMILY, variants

SOURCE = '''void f(void *base, u16 *rec)
{
    u16 a;
    u32 b;
    u32 var_s0;

    a = rec[20];
    if ((*(s16 *)((char *)((base + (a * 2))) + 0x1BC)) < limit[a * 2]) {
        b = rec[21];
        if ((u8) (*(u8 *)((char *)((base + (b * 8))) + 0x1FC)) < 3) {
            ((u16 (*)[0x1]) base)[b][0xde] += var_s0;
        }
    }
}
'''


def made(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_every_sum_gets_a_pointer_local_in_one_child_and_each_alone():
    texts = made()
    assert len(texts) == 4
    everything = texts[0]
    assert everything.count('__repair_ptr') == 12 or 'void *__repair_ptr3;' in everything
    assert '__repair_ptr1 = base + (a * 2);' in everything
    assert '(*(s16 *)((char *)(__repair_ptr1) + 0x1BC)) < limit[a * 2]' in everything
    assert '__repair_ptr2 = base + (b * 8);' in everything
    assert '__repair_ptr3 = base + (b * 2);' in everything
    assert '(*(u16 *)((char *)(__repair_ptr3) + 0x1BC)) += var_s0;' in everything
    assert '[0xde]' not in everything
    for one in texts[1:]:
        assert one.count(' = base + (') == 1


def test_the_assignment_goes_on_its_own_line_before_the_statement_with_its_indent():
    text = made()[0]
    lines = text.splitlines()
    at = next(i for i, line in enumerate(lines) if '__repair_ptr2 = ' in line)
    assert lines[at].startswith('        __repair_ptr2') and 'if ((u8)' in lines[at + 1]


def test_a_sum_that_calls_or_sits_behind_else_stays():
    called = made(SOURCE.replace('base + (a * 2)', 'pick(a) + (a * 2)'))
    assert called and all('((char *)((pick(a) + (a * 2))) + 0x1BC)' in text for text in called)
    other = 'void f(void *base, u16 a)\n{\n    if (a) {\n        g();\n    } else if ((*(s16 *)((char *)((base + (a * 2))) + 4)) < 3) {\n        h();\n    }\n}\n'
    assert not made(other)
