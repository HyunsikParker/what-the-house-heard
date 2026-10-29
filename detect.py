"""Ask TabPFN which rooms were occupied, minute by minute, then list the presences nobody walked to.

usage: python detect.py DATA_DIR OUT_JSON [--model-path CKPT] [--train-rows 3000] [--device cpu]

TabPFN learns occupancy in context from the labelled ordinary nights in DATA_DIR/train.csv (no gradient training) and
scores every room-minute of DATA_DIR/halloween.csv. A presence counts as unexplained when the room looks occupied for at
least two minutes, nobody crossed the hallway in the three minutes before, and the bedroom still looks occupied.
"""
import argparse
import json
import time

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, precision_score, recall_score

from features import FEATURES, ROOMS, build


def fit_predict(train, test, args, seed=0):
    from tabpfn import TabPFNClassifier
    sample = train.sample(n=min(args.train_rows, len(train)), random_state=seed)
    # More than 1,000 training rows on a CPU is slow by TabPFN's standards but takes about a minute here.
    kwargs = dict(device=args.device, random_state=seed, n_estimators=args.estimators, ignore_pretraining_limits=True)
    if args.model_path:
        kwargs["model_path"] = args.model_path
    clf = TabPFNClassifier(**kwargs)
    clf.fit(sample[FEATURES].to_numpy(np.float32), sample["occupied"].to_numpy())
    return clf.predict_proba(test[FEATURES].to_numpy(np.float32))[:, 1]


def runs(mask):
    """(start, end) index pairs of consecutive True values, end exclusive."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        if not v and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out


def events(night, threshold=0.5):
    piv = {c: night.pivot(index="minute", columns="room", values=c) for c in ("p", "motion", "co2", "light", "sound", "humidity", "door")}
    p, motion = piv["p"], piv["motion"]
    times = night.drop_duplicates("minute").set_index("minute")["time"]
    out = []
    for room in ROOMS:
        if room == "bedroom":
            continue
        occupied = (p[room] > threshold).to_numpy()
        for s, e in runs(occupied):
            if e - s < 2:
                continue
            # A walk shows up as hallway occupancy or hallway motion in the three minutes before (the motion sensor alone
            # can miss a quick walk).
            window = slice(max(0, s - 3), s + 1)
            walked = room == "hallway" or (p["hallway"].iloc[window] > threshold).any() or motion["hallway"].iloc[window].sum() > 0
            in_bed = p["bedroom"].iloc[s] > threshold
            seg = slice(s, e)
            out.append({
                "room": room, "start": times.iloc[s], "end": times.iloc[e - 1], "minutes": e - s,
                "kind": "explained" if walked or not in_bed else "unexplained",
                "why": ("someone crossed the hallway just before" if walked else "nobody crossed the hallway first")
                       + ("; the bedroom still looked occupied" if in_bed else "; the bedroom looked empty"),
                "peak_probability": round(float(p[room].iloc[seg].max()), 3),
                "co2_change_ppm": round(float(piv["co2"][room].iloc[e - 1] - piv["co2"][room].iloc[s]), 1),
                "light_max_lux": round(float(piv["light"][room].iloc[seg].max()), 1),
                "sound_max_dba": round(float(piv["sound"][room].iloc[seg].max()), 1),
                "humidity_max_pct": round(float(piv["humidity"][room].iloc[seg].max()), 1),
                "motion_triggers": int(motion[room].iloc[seg].sum()),
            })
    for i in np.flatnonzero(piv["door"]["hallway"].to_numpy() > 0):
        moved = motion["hallway"].iloc[max(0, i - 2):i + 3].sum()
        out.append({"room": "hallway", "start": times.iloc[i], "end": times.iloc[i], "minutes": 1,
                    "kind": "unexplained" if moved == 0 else "explained",
                    "why": "the front door contact opened" + (" and the hallway motion sensor saw nothing" if moved == 0 else ""),
                    "peak_probability": round(float(p["hallway"].iloc[i]), 3), "motion_triggers": int(moved)})
    return sorted(out, key=lambda r: (r["start"] < "22", r["start"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--model-path", default=None)
    ap.add_argument("--train-rows", type=int, default=3000)
    ap.add_argument("--estimators", type=int, default=4)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()
    train = build(pd.read_csv(f"{args.data}/train.csv"))
    night = build(pd.read_csv(f"{args.data}/halloween.csv"))

    nights = sorted(train["night"].unique())
    held = train[train["night"] == nights[-1]]
    t0 = time.time()
    ph = fit_predict(train[train["night"] != nights[-1]], held, args)
    yh, ypred = held["occupied"].to_numpy(), (ph > 0.5).astype(int)
    check = {"held_out_night": nights[-1], "rows": int(len(held)), "balanced_accuracy": round(balanced_accuracy_score(yh, ypred), 4),
             "precision": round(precision_score(yh, ypred), 4), "recall": round(recall_score(yh, ypred), 4),
             "seconds": round(time.time() - t0, 1)}
    print("held-out check:", check)

    t0 = time.time()
    night["p"] = fit_predict(train, night, args)
    report = {"night": str(night["night"].iloc[0]), "check": check, "score_seconds": round(time.time() - t0, 1),
              "events": events(night),
              "timeline": {r: night[night["room"] == r].sort_values("minute")["p"].round(3).tolist() for r in ROOMS},
              "times": night[night["room"] == ROOMS[0]].sort_values("minute")["time"].tolist()}
    with open(args.out, "w") as f:
        json.dump(report, f, indent=1)
    for e in report["events"]:
        print(e["start"], e["room"], e["kind"], "-", e["why"])


if __name__ == "__main__":
    main()
