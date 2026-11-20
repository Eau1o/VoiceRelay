TYPELESS = "TYPELESS"
WETYPE = "WETYPE"


def engine_for(name, overrides, used, threshold):
    engine = overrides.get(name.lower(), TYPELESS)
    return WETYPE if engine == TYPELESS and used >= threshold else engine
