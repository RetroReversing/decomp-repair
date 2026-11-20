from decomprepair import observed_arithmetic_repairs as arithmetic
from decomprepair import observed_flow_repairs as flow
from decomprepair import observed_storage_repairs as storage
from decomprepair import targeted_switch_labels


def test_switch_changes_only_existing_explicit_labels_and_rejects_two_matching_switches():
    code = 'int f(int k) { switch (k) { case 1: case 3: return 9; case 2: return 4; } return 0; }'
    diff = [{'table':100,'case':2,'target':10,'candidate':20},
            {'table':100,'case':3,'target':20,'candidate':10}]
    [(_, candidate)] = targeted_switch_labels.variants(code,'f',diff)
    assert 'case 1: case 2: return 9; case 3: return 4;' in candidate
    duplicate = 'switch (k) { case 2: break; case 3: break; }'
    assert not targeted_switch_labels.variants(code.replace('return 0;',duplicate+' return 0;'),'f',diff)
    assert not targeted_switch_labels.variants(code.replace('case 2:', 'case OTHER:'),'f',diff)


def test_reload_checks_actual_record_type_and_preserves_adjacent_store_order():
    header = 'typedef struct { float a; int flag; float b; } Vec;'
    source = 'void f(Vec *p) { p->a = 1.0f; p->flag = 0; p->b = p->a; }'
    [(_, candidate)] = storage.staged_reload(source,'f',header,4)
    assert 'p->a = 1.0f; repair_reload = *(volatile float *)&(p->a); p->flag = 0;' in candidate
    assert 'p->b = repair_reload;' in candidate
    assert not storage.staged_reload(source,'f',header,8)
    assert not storage.staged_reload(source,'f',header.replace('float a','int a') +
                                     'struct Other { float a; };',4)
    assert not storage.staged_reload(source.replace('p->flag = 0;', 'g(p);'),'f',header,4)


def test_stack_adjustment_never_shrinks_a_used_donor():
    source = 'void f(void) { float dead[4]; float buf[2]; fill(buf); }'
    assert storage.redistribute(source,'f','',[4]) == [
        (storage.STACK,source.replace('dead[4]', 'dead[3]').replace('buf[2]', 'buf[3]'))]
    assert not storage.redistribute(source.replace('fill(buf);','fill(dead); fill(buf);'),'f','',[4])
    assert not storage.redistribute(source.replace('fill(buf);','t=sizeof(buf); fill(buf);'),'f','',[4])
    assert not storage.redistribute(source,'f','',[0,3])


def test_first_read_keeps_one_read_and_rejects_an_observable_next_initializer():
    source = 'void f(void) { int **p; int *q; p = A; q = B; if (*p) call(q); }'
    [(_, candidate)] = flow.first_read(source,'f','#define UNUSED 7')
    assert candidate.count('= *p;') == 1
    assert 'repair_first_entry = *p; q = B; if (repair_first_entry)' in candidate
    assert not flow.first_read(source.replace('q = B;','q = get();'),'f','')
    assert not flow.first_read(source.replace('if (*p)','if (*p == mutate())'),'f','')
    assert not flow.first_read(source,'f','#define A get()')
    assert flow.first_read(source.replace('if (*p)','if (*p != NULL)'),'f','#define NULL ((void *)0)')


def test_guard_initializer_respects_liveness_and_aliases():
    source = 'void f(int a) { int n; if (a) { n = 0; while (n<a) n++; } }'
    assert len(flow.guarded_initializer(source,'f','',{0})) == 1
    assert not flow.guarded_initializer(source.replace('if (a)','if (a && n)'),'f','',{0})
    assert not flow.guarded_initializer(source.replace('if (a)','save(&n); if (a)'),'f','',{0})


def test_sentinel_loop_does_not_move_a_read_past_continue():
    source = ('void f(void) { u16 s; u16 *p; p = A; s = *p; if (s != 65535) {'
              ' do { use(s); p++; s = *p; } while (s != 65535); } }')
    assert len(flow.sentinel_loop(source,'f','',{65535})) == 1
    assert not flow.sentinel_loop(source.replace('use(s);','if (c) continue; use(s);'),'f','',{65535})
    assert not flow.sentinel_loop(source,'f','',{32767})


def test_arithmetic_eligibility_leaves_live_values_and_wrong_shapes_untouched():
    square = 'float f(void) { float x; float y; x = a; y = b; g(x*x + y*y); return x; }'
    assert not arithmetic.squared_terms(square,'f','')
    division = 'int f(void) { int n; int q; n = a; q = n / 192000; return q; }'
    assert not arithmetic.separated_divisions(division,'f','',[(1000,192)])
    assert not arithmetic.separated_divisions(division.replace('int n;', 'u32 n;'),'f','',[(1000,196)])
    minmax = ('int f(void) { int a; int b; int x; int y; x = p; y = q; a = x-u; b = y-v; '
              'out = (a < b) ? a : b; return x; }')
    assert not arithmetic.in_place_minmax(minmax,'f','')
