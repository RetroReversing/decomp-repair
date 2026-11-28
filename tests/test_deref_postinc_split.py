"""`x = *p++;` written as the read and then the step."""
from decomprepair import deref_postinc_split as m
from decomprepair import registry

SOURCE = '''void walk(unsigned char *in)
{
    int a;
    int b;
    a = *in++;
    if (a) b = *in++;
    b = *in--;
    use(a, b, &in);
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'walk')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_each_read_is_split_and_all_together():
    found = texts()
    assert any('a = *in;\n    in++;' in t and 'b = *in--;' in t for t in found)
    assert any('a = *in;\n    in++;' in t and 'b = *in;\n    in--;' in t for t in found)


def test_an_unbraced_condition_body_is_left_alone():
    assert all('if (a) b = *in++;' in t for t in texts())


def test_it_is_registered():
    repair = registry.get('deref_postinc_split')
    assert repair and registry.problems(repair) == []
