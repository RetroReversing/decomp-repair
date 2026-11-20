from decomprepair import target_schedule_repairs as repairs


def propose(text, rewrite, *args):
    return [source for _,source in repairs.variants(text,'f','',[(rewrite,args)])]


def test_shift_preserves_the_intervening_base_load():
    text = ('int *f(int i,int **table) { int offset=(i<<2)+i; int *p=table[0]; '
            'offset=(offset<<2)-20; return p+offset; }')
    [candidate] = propose(text,repairs.offset_shift,{2})
    assert '<< 2; int *p=table[0]; offset=offset-20;' in candidate
    assert not propose(text.replace('table[0]','table[offset]'),repairs.offset_shift,{2})
    assert not propose(text,repairs.offset_shift,{3})


def test_fallback_on_edge_preserves_the_conversion_and_store():
    text = ('void f(float x,int *p) { int a; a=1; if (x == 0) { goto out; } '
            'a=(unsigned int)x; out: *p=a; }')
    [candidate] = propose(text,repairs.clamp_fallback,{1})
    assert 'if (x == 0) { a = 1; goto out; } a=(unsigned int)x; out: *p=a;' in candidate
    assert not propose(text.replace('x == 0','a == 0'),repairs.clamp_fallback,{1})


def test_shared_label_does_not_run_the_null_check_on_the_bound_edge():
    text = ('int f(int i,int n) { int a; if (i<n) { a=0; goto out; } '
            'if (n != 0) { a=n; goto out; } a=0; out: return a; }')
    [candidate] = propose(text,repairs.shared_zero)
    assert 'goto repair_absent;' in candidate
    assert 'repair_absent: a=0; out: return a;' in candidate
    assert not propose(text.replace('a=0; out','a=2; out'),repairs.shared_zero)
