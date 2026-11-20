from decomprepair import target_inline_storage_repairs as repairs


def propose(source,rewrite,witness=True):
    return [text for _,text in repairs.variants(source,'f','',[(rewrite,witness)])]


def test_shared_return_checks_all_call_sites():
    text = ('static inline int h(int x,int y) { if (!x) return 0; if (!y) return 0; return y; } '
            'int f(int a,int b) { return (short)h(a,b); }')
    [new] = propose(text,repairs.shared_signed_return)
    assert new.count('goto repair_return;')==2
    assert 'repair_return: return (short)repair_status;' in new
    assert not propose(text+' int g(int a) { return h(a,a); }',repairs.shared_signed_return)


def test_address_split_keeps_byte_stride_and_const():
    text = 'int f(const unsigned char *p,int i) { return *(p + (i<<2)); }'
    [new] = propose(text,repairs.split_byte_address)
    assert 'const unsigned char *repair_byte_address = p; repair_byte_address += (i<<2);' in new
    assert not propose(text.replace('unsigned char','unsigned short'),repairs.split_byte_address)


def test_float_local_must_be_dead_after_the_new_assignment():
    text = ('void work(void); float f(float u,float v) { float early,late; early=u*v; consume(early); '
            'late=u-v; work(); return late; }')
    [new] = propose(text,repairs.reuse_dead_float,{'work'})
    assert 'early=u-v; work(); return early;' in new
    assert not propose(text.replace('return late','return late+early'),repairs.reuse_dead_float,{'work'})
