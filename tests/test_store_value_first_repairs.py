from decomprepair.store_value_first_repairs import variants

SOURCE = """void setup(Cam *cam, s32 i) {
    rs->a[i].h[0] = (s16) ((s32) (2.0f * (cam->scale * cam->width)));
    rs->a[i].h[1] = 0xFF;
    rs->a[i].h[2] = (s16) ((s32) (cam->zoom * 4.0f));
    rs->a[i].h[3] = (s16) ((s32) (cam->tilt * 4.0f));
    use(i);
}
"""


def test_each_float_store_gets_its_value_computed_first():
    candidates = {c for _, c in variants(SOURCE, 'setup')}
    every = max(candidates, key=lambda c: c.count('tv'))
    assert 'tv1 = (s16) ((s32) (2.0f * (cam->scale * cam->width)));\n    rs->a[i].h[0] = tv1;' in every
    assert 'tv2 = (s16) ((s32) (cam->zoom * 4.0f));\n    rs->a[i].h[2] = tv2;' in every
    assert 'tv3 = ' in every and '  s16 tv1;' in every and '  s16 tv3;' in every
    assert 'rs->a[i].h[1] = 0xFF;' in every  # an integer constant store stays


def test_one_store_and_a_run_are_offered_beside_all_of_them():
    candidates = [c for _, c in variants(SOURCE, 'setup')]
    counts = sorted({c.count(' = tv') for c in candidates})
    assert counts[0] == 1 and counts[-1] == 3 and len(candidates) >= 3


def test_stores_with_a_call_or_no_float_are_left_alone():
    plain = "void f(Cam *c, s32 i) {\n    rs->a[i].h[0] = (s16) (c->x + 1);\n}\n"
    assert not variants(plain, 'f')
    called = "void f(Cam *c, s32 i) {\n    rs->a[i].h[0] = (s16) (g(c) * 4.0f);\n}\n"
    assert not variants(called, 'f')


def test_a_name_already_used_is_not_taken_again():
    taken = SOURCE.replace('void setup(Cam *cam, s32 i) {', 'void setup(Cam *cam, s32 i) {\n    s32 tv1;')
    assert all('s16 tv1;' not in c for _, c in variants(taken, 'setup'))
