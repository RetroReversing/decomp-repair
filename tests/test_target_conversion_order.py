from decomprepair import target_conversion_order_repairs as repairs


def propose(source, repair, *evidence):
    return [text for _,text in repairs.variants(source,'f','',[(repair,evidence)])]


def test_inequality_preserves_conditional_call_and_rejects_escaped_word():
    source = ('int f(int word, int test) { int tmp; tmp = word ^ 0x20; '
              'if (test) { visit(word); } return tmp != 0; }')
    [new] = propose(source,repairs.inequality,{('visit',32)})
    assert 'if (test) { visit(word); } return word != 0x20;' in new
    assert not propose(source.replace('visit(word)','visit(&word)'),repairs.inequality,{('visit',32)})
    assert not propose(source,repairs.inequality,{('visit',31)})


def test_float_argument_carriers_must_be_dead_and_signed():
    source = ('int f(int first, int second, float x, float y) { int a, b; '
              'a = (int)x; b = (int)y; return (a << 8) | b; }')
    [new] = propose(source,repairs.argument_carriers,(0,1))
    assert 'first = (int)x; second = (int)y; return (first << 8) | second;' in new
    assert not propose(source.replace('| b','| b | first'),repairs.argument_carriers,(0,1))
    assert not propose(source.replace('int first','unsigned first'),repairs.argument_carriers,(0,1))


def test_float_products_swap_only_plain_independent_statements():
    source = ('float f(float a,float b,float shared) { float x,y; '
              'x=-a*shared; y=b*shared; return x-y; }')
    [new] = propose(source,repairs.float_products,'s')
    assert 'y=b*shared; x=-a*shared; return x-y;' in new
    assert not propose(source.replace('y=b*shared','y=x*shared'),repairs.float_products,'s')
    assert not propose(source.replace('x=-a*shared','if (a) x=-a*shared'),repairs.float_products,'s')
