from decomprepair import lockstep_cursor_index as r

SOURCE = '''void f(u32 k, u32 n) {
    u32 i;
    {
        u32 *bb = D_B + k;
        u32 *cc = D_C + k;
        i = 0;
        do {
            D_A[i] = (*bb << 7) + *cc;
            i++;
            bb++;
            cc++;
            k++;
        } while (i < n);
    }
}
'''


def test_cursors_stepped_with_the_counter_become_the_counters_index():
    found = r.variants(SOURCE, 'f')
    assert [family for family, _ in found] == [r.FAMILY, r.FAMILY, r.FAMILY]
    everything = found[0][1]
    assert 'D_A[i] = (D_B[k] << 7) + D_C[k];' in everything
    assert 'bb' not in everything and 'cc' not in everything and 'k++;' in everything
    assert 'D_B + k' not in everything


def test_each_cursor_alone_is_also_offered():
    _, only_bb, only_cc = r.variants(SOURCE, 'f')
    assert 'D_B[k]' in only_bb[1] and '*cc' in only_bb[1] and 'cc++;' in only_bb[1]
    assert 'D_C[k]' in only_cc[1] and '*bb' in only_cc[1]


def test_a_read_between_the_two_steps_is_left_alone():
    source = SOURCE.replace('bb++;\n            cc++;\n            k++;', 'bb++;\n            D_A[i] = *cc;\n            cc++;\n            k++;')
    kinds = r.variants(source, 'f')
    assert all('D_C[k]' in text or 'D_B[k]' in text for _, text in kinds)


def test_a_cursor_used_after_the_loop_or_not_a_dereference_is_left_alone():
    after = SOURCE.replace('    }\n}', '    }\n    D_A[0] = *bb;\n}')
    assert not [1 for _, text in r.variants(after, 'f') if 'D_B[k]' in text]
    plain = SOURCE.replace('(*bb << 7)', '(g(bb) << 7)')
    assert not [1 for _, text in r.variants(plain, 'f') if 'D_B[k]' in text]


def test_a_counter_assigned_in_the_loop_or_between_start_and_loop_is_left_alone():
    assigned = SOURCE.replace('i = 0;', 'i = 0;\n        k = i;')
    assert not r.variants(assigned, 'f')
    inside = SOURCE.replace('k++;', 'k++;\n            k += 2;')
    assert not r.variants(inside, 'f')


STRIDE = '''void f(u16 *tab, u32 ix, u32 step) {
    do {
        u16 *w = tab + ix;
        do {
            *w = ix + 1;
            w += step;
            ix += step;
        } while ((ix >> 4) == 0);
    } while (g());
}
'''


def test_cursor_and_counter_that_step_by_the_same_amount_are_folded():
    found = r.variants(STRIDE, 'f')
    assert found and 'tab[ix] = ix + 1;' in found[0][1]
    assert 'w' not in found[0][1].replace('while', '').replace('tab', '')


def test_different_strides_are_left_alone():
    assert not r.variants(STRIDE.replace('w += step;', 'w += 2;'), 'f')
