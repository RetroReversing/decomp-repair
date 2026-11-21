from decomprepair import residual_source_repairs as repair


def test_tail_redirect_requires_an_unescaped_local_flag():
    source = 'int f(int i) { int v; if (i != 26) { return 0; } v = i < 30; tail: return v ? 1 : 0; }'
    variants = repair.zero_exit(source, 'f', '')
    assert len(variants) == 2
    assert any('v = 0; goto tail' in text for _, text in variants)
    assert not repair.zero_exit(source.replace('int v;', 'extern int v;'), 'f', '')


def test_hoist_only_the_pointer_call_with_stable_siblings():
    source = ('extern unsigned char data[]; short *lookup(int); void consume(char *, short *);\n'
              'void f(char *out) { consume(out, lookup(data[0])); }')
    [(family, text)] = repair.call_lifetimes(source, 'f', '')
    assert family == repair.CALL and 'short *__repair_call_value = lookup(data[0]);' in text
    assert not repair.call_lifetimes(source.replace('consume(out,', 'consume(next(out),'), 'f', '')


def test_entry_carriers_keep_pointer_roles():
    source = 'int f(char *state, int *a, int *b) { char *p; int x; p = *state; x = p[0]; return x + *a + *b; }'
    variants = repair.entry_lifetimes(source, 'f', '')
    assert len(variants) == 2
    assert all('*__repair_entry_a + *__repair_entry_b' in text for _, text in variants)
    assert not repair.entry_lifetimes(source.replace('return x', 'a++; return x'), 'f', '')


def test_frame_address_is_rebuilt_from_a_stable_local_index():
    source = ('extern int table; int run(int); void f(int i) { int off; int idx; int *p; '
              'idx = i; off = idx * 4; p = (int *)((char *)&table + off); *p = run(1); }')
    variants = repair.frame_address(source, 'f', '')
    assert len(variants) == 2
    assert any('idx * 4' in text.split('__repair_frame_result =')[1] for _, text in variants)
    assert not repair.frame_address(source.replace('*p = run', 'off++; *p = run'), 'f', '')


def test_buffer_preparation_preserves_both_call_argument_types():
    source = ('extern int buffer; void f(int x) { format((char *)&buffer, x); '
              'notify(x, x, &buffer, 0); }')
    [(family, text)] = repair.buffer_preparation(source, 'f', '')
    assert family == 'residual_call_buffer' and '(__typeof__(&buffer))__repair_message_buffer' in text


def test_duplicate_call_setup_branches_on_a_live_parameter():
    source = ('void f(int arg) { int x; int y; if (arg < 0) { return; } '
              'else { x = 4; y = get(x); do { sink(y); } while (0); } }')
    [(family, text)] = repair.duplicate_call_setup(source,'f','')
    assert family == repair.CALL and 'if (arg)' in text and text.count('y = get(x);') == 2
    assert not repair.duplicate_call_setup(source.replace('if (arg < 0)','if ((arg = -1) < 0)'),'f','')


def test_evidenced_implicit_pointer_updates_prototype_and_call():
    source = 'float dist(void *); float f(char *s, float *p) { return dist(s + 4); }'
    [(family, text)] = repair.forward_second_pointer(source,'f','','dist')
    assert family == repair.ENTRY and 'dist(void *, float *)' in text and 'dist(s + 4, p)' in text
    assert not repair.forward_second_pointer(source,'f','float dist(void *);','dist')
