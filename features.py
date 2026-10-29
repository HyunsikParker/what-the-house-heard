"""Per-room, per-minute features from the raw sensor columns. The whole night is analysed after the fact, so windows
may look a minute ahead as well as back."""
import numpy as np

ROOMS = ["bedroom", "hallway", "kitchen", "living_room"]
FEATURES = ["room_id", "tod_sin", "tod_cos", "co2", "co2_rise5", "co2_above_floor", "light_log", "sound_above_median",
            "motion3", "temp_rise10", "humidity_above_median", "door"]


def build(df):
    df = df.sort_values(["night", "room", "minute"]).copy()
    g = df.groupby(["night", "room"], sort=False)
    df["room_id"] = df["room"].map({r: i for i, r in enumerate(ROOMS)})
    hour = 22 + df["minute"] / 60.0
    df["tod_sin"] = np.sin(2 * np.pi * hour / 24)
    df["tod_cos"] = np.cos(2 * np.pi * hour / 24)
    df["co2_rise5"] = (df["co2"] - g["co2"].shift(5)).fillna(0.0)
    df["co2_above_floor"] = df["co2"] - g["co2"].transform(lambda s: s.rolling(90, min_periods=1).min())
    df["light_log"] = np.log1p(df["light"].clip(lower=0))
    df["sound_above_median"] = df["sound"] - g["sound"].transform("median")
    df["motion3"] = g["motion"].transform(lambda s: s.rolling(3, center=True, min_periods=1).sum())
    df["temp_rise10"] = (df["temp"] - g["temp"].shift(10)).fillna(0.0)
    df["humidity_above_median"] = df["humidity"] - g["humidity"].transform(lambda s: s.rolling(31, center=True, min_periods=1).median())
    return df
