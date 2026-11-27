from decomprepair.call_statement_expression import variants

SOURCE = '''float root(float);
extern short table[];
void f(int n) {
 int i;
 for (i = 0; i < 8; i++) {
  table[i] = table[i + 8] = root(i * 2.0f) * n;
 }
}
'''


def test_wraps_the_call_of_a_computed_store():
    [(family, child)] = variants(SOURCE, 'f')
    assert family == 'call_statement_expression'
    assert 'table[i] = table[i + 8] = ({ root(i * 2.0f); }) * n;' in child
    assert variants(child, 'f') == []


def test_a_plain_variable_or_no_call_is_left_alone():
    assert variants('int g(void);\nint x;\nvoid f(void) { int y; y = g(); x = y; }\n', 'f') == []
    assert variants('int t[4];\nvoid f(int i) { t[i] = i + (i * 2); }\n', 'f') == []


def test_two_stores_also_wrap_together():
    source = 'int g(void);\nint t[4];\nvoid f(void) { t[0] = g(); t[1] = g(); }\n'
    children = [child for _, child in variants(source, 'f')]
    assert len(children) == 3
    assert children[-1].count('({ g(); })') == 2
