"""A constant result returned where it's decided."""
from decomprepair import returned_flag_repairs as r

SOURCE = '''s32 f(void *arg0) {
    s32 var_v0;
    void *temp_v1;

    temp_v1 = M2C_FIELD(arg0, void **, 0x68);
    var_v0 = 0;
    if (M2C_FIELD(temp_v1, s32 *, 0x64) != 0) {
        var_v0 = 0;
        if (!(M2C_FIELD(temp_v1, s32 *, 0x14) & 0x10)) {
            var_v0 = 1;
            M2C_FIELD(temp_v1, f32 *, 0x20) = -M2C_FIELD(temp_v1, f32 *, 0x20);
        }
    }
    return var_v0;
}
'''


def test_returns_the_constants():
    # An N64 function at 80.7%: exact so.
    (family, out), = r.variants(SOURCE, 'f')
    assert family == 'returned_flag'
    assert 'var_v0' not in out
    assert '''        if (!(M2C_FIELD(temp_v1, s32 *, 0x14) & 0x10)) {
            M2C_FIELD(temp_v1, f32 *, 0x20) = -M2C_FIELD(temp_v1, f32 *, 0x20);
            return 1;
        }
    }
    return 0;
}''' in out


def test_left_alone_otherwise():
    assert r.variants(SOURCE.replace('var_v0 = 1;', 'var_v0 = arg0 != 0;'), 'f') == []  # not a constant
    assert r.variants(SOURCE.replace('            M2C_FIELD(temp_v1, f32 *, 0x20) =', '            g(var_v0);\n            M2C_FIELD(temp_v1, f32 *, 0x20) ='), 'f') == []
