from decomprepair import store_across_step as step

SOURCE = """void f(unsigned char *p, int c)
{
    if (c) {
        *p = c;
        p++;
        *p = 0xDE;
    }
    p++;
}
"""


def test_a_step_before_its_store_moves_after_it():
    [(family, text)] = step.variants(SOURCE, 'f')
    assert family == 'store_across_step'
    assert 'p[1] = 0xDE;\n        p++;' in text


def test_and_back():
    after = step.variants(SOURCE, 'f')[0][1]
    assert any('p++;\n        *p = 0xDE;' in text for _, text in step.variants(after, 'f'))


def test_a_value_that_reads_the_pointer_stays():
    assert step.variants(SOURCE.replace('*p = 0xDE;', '*p = p[-1];'), 'f') == []
