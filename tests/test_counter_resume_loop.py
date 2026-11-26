from decomprepair import counter_resume_loop, integer_sum_repairs

SOURCE = '''void fill(void)
{
    s32 i;
    u32 k;

    i = 0;
    do {
        table[(i & 0xFF) * 5] = 0;
        i++;
    } while ((u32) (i & 0xFF) < count);
    k = i & 0xFF;
    while (k < 200) {
        char *p;
        p = table + (k * 4) + k;
        p[0] = 4;
        k = (k + 1) & 0xFF;
    }
}
'''


def sources(source):
    return [child for _, child in counter_resume_loop.variants(source, 'fill')]


def test_loop_resumes_the_first_counter_with_its_companions():
    out = sources(SOURCE)
    resumed = '''    while ((i & 0xFF) < 200) {
        char *p;
        k = i & 0xFF;
        p = table + (k * 4) + k;
        p[0] = 4;
        i++;
    }
}
'''
    assert out[0].endswith(resumed) and '    s32 i;' in out[0]
    combined = [child for child in out if '    u8 i;' in child and 'p = table + k * 5;' in child]
    assert len(combined) == 1
    assert 'while ((i & 0xFF) < 200)' in combined[0]


def test_for_header_form():
    source = SOURCE[:SOURCE.index('    k = i')] + '''    for (k = i & 0xFF; k < 200; k = (k + 1) & 0xFF) {
        table[k * 5] = 4;
    }
}
'''
    assert 'k = i & 0xFF;\n        table[k * 5] = 4;\n        i++;' in sources(source)[0]


def test_declined_when_a_value_is_read_after_the_loop():
    assert not sources(SOURCE.replace('    }\n}\n', '    }\n    use(k);\n}\n'))
    assert not sources(SOURCE.replace('    }\n}\n', '    }\n    use(i);\n}\n'))
    assert not sources(SOURCE.replace('p[0] = 4;', 'p[0] = 4; i = 3;'))


def test_counter_read_whole_is_not_narrowed():
    out = sources(SOURCE.replace('table[(i & 0xFF) * 5] = 0;', 'table[i * 5] = 0;'))
    assert out and all('    s32 i;' in child for child in out)


def test_byte_cast_base_sum_is_written_index_first():
    source = 'void g(s32 base, s32 i)\n{\n    u8 *p;\n    p = (u8 *) base + (i & 0xFF) * 5;\n    p[0] = 0;\n}\n'
    out = [child for _, child in integer_sum_repairs.variants(source, 'g')]
    assert any('p = (void *) (((i & 0xFF) * 5) + (s32) base);' in child for child in out)
