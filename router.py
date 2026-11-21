TYPELESS = "TYPELESS"
WETYPE = "WETYPE"


def engine_for(name, overrides):
    return overrides.get(name.lower(), TYPELESS)
