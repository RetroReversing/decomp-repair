"""Products used twice each, computed into locals together before their first use."""
from decomprepair import shared_product_repairs as p

SOURCE = '''void f(float m[4][4], float a, float x, float y)
{
	float	s;
	float	c;
	float	t;

	s = g(a);
	c = h(a);
	t = 1 - c;
	k(m);

	t = x * x;
	m[1][0] = t - (x * s);
	m[0][1] = t + (x * s);
	m[2][0] = c - (y * s);
	m[0][2] = c + (y * s);
}
'''


def test_the_products_go_together_into_locals():
    # An N64 matrix builder borrowed from another SDK release: exact with the locals together after the call.
    outs = [text for _, text in p.variants(SOURCE, 'f')]
    assert outs
    together = ('\t__repair_x_s = x * s;\n\t__repair_y_s = y * s;\n')
    assert any(together + '\tk(m);' in o or 'k(m);\n' + together in o or together + '\n\tt = x * x;' in o
               or together in o for o in outs)
    for out in outs:
        assert '(x * s)' not in out and '(y * s)' not in out
        assert '\tfloat __repair_x_s;\n\tfloat __repair_y_s;\n' in out
        # never above the write to an operand
        assert out.index('__repair_x_s = x * s;') > out.index('s = g(a);')


def test_left_alone_otherwise():
    once = SOURCE.replace('\tm[0][1] = t + (x * s);\n', '').replace('\tm[0][2] = c + (y * s);\n', '')
    assert p.variants(once, 'f') == []  # each product only once
    mixed = SOURCE.replace('float x, float y', 'int x, float y')
    assert p.variants(mixed, 'f') == []  # operands of different types


def test_propose_finds_it():
    from decomprepair.propose import propose
    assert any(q.module == 'shared_product_repairs' for q in propose(SOURCE, 'f').proposals)
