def degrees_to_0_360(number):
    """float: Convert angle (degrees) to range [0, 360)."""
    return float(number) % 360

def degrees_to_n180_180(number):
    """float: Convert angle (degrees) to range (-180, 180]"""
    return 180 - (180-float(number)) % 360
