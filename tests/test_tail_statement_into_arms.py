"""The statement after a two-arm `if`/`else` at a loop body's end, written in both arms."""
from decomprepair import registry
from decomprepair import tail_statement_into_arms as p

SOURCE = '''void draw(int n)
{
    int j;

    for (j = 0; j < n; j++) {
        if (j == 0) {
            load(0);
        } else {
            load(j);
        }
        tris(j, j + 1);
    }
}
'''


def test_the_statement_ends_both_arms():
    [(family, text)] = p.variants(SOURCE, 'draw')
    assert family == p.FAMILY
    assert text.count('tris(j, j + 1);') == 2
    first, second = text.split('} else {')
    assert 'tris(j, j + 1);' in first and 'tris(j, j + 1);' in second
    assert text.count('{') == text.count('}')


def test_not_for_a_jump_or_two_statements_and_it_is_registered():
    assert p.variants(SOURCE.replace('tris(j, j + 1);', 'break;'), 'draw') == []
    assert p.variants(SOURCE.replace('tris(j, j + 1);', 'tris(j); more(j);'), 'draw') == []
    assert any(p.FAMILY in repair.families for repair in registry.declared())
