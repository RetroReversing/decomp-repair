from decomprepair import target_edge_repairs as repairs


def propose(source, repair, evidence=True):
    return [text for _,text in repairs.variants(source,'f','',[(repair,evidence)])]


def test_continue_path_keeps_exactly_one_increment():
    source = 'void f(int n,int c) { int i; for (i=0;i<n;i++) { if (c) { continue; } use(i); } }'
    [new] = propose(source,repairs.increment_edge)
    assert 'for (i=0;i<n;) { if (c) { i++; goto repair_check_next; }' in new
    assert 'use(i);  i++; repair_check_next:' in new
    assert not propose(source.replace('continue','break'),repairs.increment_edge)


def test_float_reuse_cannot_overwrite_a_live_parameter():
    source = ('float first(float); float second(float); float f(float a,float b) { float r,t; '
              'r=first(a); t=second(b); a=r; return a+t; }')
    witness = {('first','second')}
    [new] = propose(source,repairs.float_call_reuse,witness)
    assert 'a = first(a); r = a; t=second(b);' in new
    assert not propose(source.replace('second(b)','second(a)'),repairs.float_call_reuse,witness)


def test_multiply_keeps_the_original_halfword_type():
    source = 'struct S { u16 scale; }; int f(struct S *p,int lo) { int v; v=p->scale; v=lo*v; return v; }'
    [new] = propose(source,repairs.narrow_multiply)
    assert 'unsigned short repair_scale = p->scale; v = lo * repair_scale;' in new
    assert not propose(source.replace('u16 scale','s16 scale'),repairs.narrow_multiply)


def test_keep_other_jumps_to_the_original_increment():
    source = ('void f(int n,int c) { int i; i=0; do { if (c) { goto step; } use(i); '
              'step: i++; } while (i<n); }')
    [new] = propose(source,repairs.increment_edge)
    assert 'if (c) { i++; goto repair_check_next; }' in new
    assert 'step: i++;  repair_check_next:' in new
