"""Generate synthetic night-time sensor logs for a small flat. Every value here is simulated, not measured.

usage: python simulate.py OUT_DIR [--seed 31]

Writes OUT_DIR/train.csv (seven ordinary nights with per-room occupancy labels) and OUT_DIR/halloween.csv (the night to
explain, unlabelled) plus OUT_DIR/halloween_truth.json (what the simulator actually injected, for checking the detector).
One row per room per minute from 22:00 to 07:00.
"""
import argparse
import csv
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOMS = ["bedroom", "hallway", "kitchen", "living_room"]
VOLUME_M3 = {"bedroom": 30.0, "hallway": 12.0, "kitchen": 20.0, "living_room": 45.0}
MINUTES = 540  # 22:00 -> 07:00
OUTDOOR_CO2 = 420.0
FIELDS = ["night", "time", "minute", "room", "co2", "light", "sound", "motion", "temp", "humidity", "door"]


def hhmm(minute):
    t = datetime(2000, 1, 1, 22, 0) + timedelta(minutes=minute)
    return t.strftime("%H:%M")


def at(clock):
    """Minute of the night for an HH:MM clock time between 22:00 and 07:00."""
    h, m = map(int, clock.split(":"))
    return (h - 22) * 60 + m if h >= 22 else (h + 2) * 60 + m


class Night:
    """Who is where (people, activity 0 asleep / 1 calm / 2 active) and what else happens, minute by minute."""

    def __init__(self):
        self.people = {r: [0] * MINUTES for r in ROOMS}
        self.activity = {r: [0] * MINUTES for r in ROOMS}
        self.light = {r: [None] * MINUTES for r in ROOMS}   # forced lux level, None = follow occupancy
        self.extra_sound = {r: [0.0] * MINUTES for r in ROOMS}
        self.extra_humidity = {r: [0.0] * MINUTES for r in ROOMS}
        self.door = [0] * MINUTES
        self.ghost = {r: [0] * MINUTES for r in ROOMS}      # simulated presence that no resident accounts for
        self.cat = {r: [0] * MINUTES for r in ROOMS}        # the cat sets off motion sensors but is not a person

    def cat_walk(self, start, rng):
        """The cat wanders through two or three rooms; it trips motion sensors and makes a little noise, nothing else."""
        t = start
        for room in rng.sample(["hallway", "kitchen", "living_room"], rng.choice([2, 3])):
            for tt in range(t, min(MINUTES, t + rng.randint(2, 6))):
                self.cat[room][tt] = 1
                t = tt + 1

    def stay(self, room, start, end, people=1, activity=1, lux=None):
        for t in range(max(0, start), min(MINUTES, end)):
            self.people[room][t] += people
            self.activity[room][t] = max(self.activity[room][t], activity)
            if lux is not None:
                self.light[room][t] = lux

    def move(self, start, rng, people=1, lux=None):
        """A walk through the hallway; takes one or two minutes and returns the minute of arrival."""
        steps = rng.choice([1, 2])
        self.stay("hallway", start, start + steps, people, 2, lux)
        return start + steps


def ordinary_night(rng, trips=None):
    n = Night()
    tv_end = at("22:40") + rng.randint(-10, 15)
    n.stay("living_room", 0, tv_end, 2, 2, lux=rng.uniform(150, 260))
    tea = tv_end - rng.randint(15, 25)
    n.stay("kitchen", tea, tea + rng.randint(6, 12), 1, 2, lux=rng.uniform(250, 400))
    for t in range(tea, min(MINUTES, tea + 8)):
        n.extra_humidity["kitchen"][t] += 4.0  # kettle
    t = n.move(tv_end, rng, 2, lux=rng.uniform(60, 120))
    sleep = t + rng.randint(15, 40)
    n.stay("bedroom", t, sleep, 2, 1, lux=rng.uniform(80, 160))
    wake = at("06:35") + rng.randint(-10, 15)
    n.stay("bedroom", sleep, wake, 2, 0, lux=None)
    count = rng.choice([0, 1, 1, 2]) if trips is None else len(trips)
    starts = trips or sorted(rng.sample(range(sleep + 60, wake - 60, 7), count))
    for s in starts:  # one resident gets up for a glass of water
        k = n.move(s, rng, 1, lux=rng.uniform(4, 12))
        stay = rng.randint(3, 6)
        n.stay("kitchen", k, k + stay, 1, 1, lux=rng.uniform(25, 60))
        back = n.move(k + stay, rng, 1, lux=rng.uniform(4, 12))
        for tt in range(s, back):
            n.people["bedroom"][tt] -= 1
    if rng.random() < 0.5:  # a resident cannot sleep and sits in the dark living room with a phone
        s = rng.randint(sleep + 45, wake - 120)
        k = n.move(s, rng, 1, lux=rng.uniform(3, 8))
        stay = rng.randint(15, 35)
        n.stay("living_room", k, k + stay, 1, 1, lux=rng.uniform(2, 8))
        back = n.move(k + stay, rng, 1, lux=rng.uniform(3, 8))
        for tt in range(s, back):
            n.people["bedroom"][tt] -= 1
    if rng.random() < 0.4:  # the living-room lamp stays on after everyone has gone to bed
        lamp_off = rng.randint(at("00:00"), at("01:30"))
        for tt in range(tv_end, lamp_off):
            n.light["living_room"][tt] = rng.uniform(90, 110)
    for _ in range(rng.choice([1, 2, 3])):
        n.cat_walk(rng.randint(sleep + 10, wake - 30), rng)
    n.stay("bedroom", wake, MINUTES, 1, 2, lux=rng.uniform(120, 200))
    k = n.move(wake + 3, rng, 1, lux=rng.uniform(60, 120))
    n.stay("kitchen", k, MINUTES, 1, 2, lux=rng.uniform(250, 400))
    for tt in range(k, min(MINUTES, k + 8)):
        n.extra_humidity["kitchen"][tt] += 5.0
    return n, sleep, wake


def haunt(n, rng):
    """Presence the residents cannot account for: nobody walks there, both stay in bed, yet the room reacts."""
    events = [
        {"room": "living_room", "start": at("02:47"), "end": at("02:56"), "lux": rng.uniform(0.0, 2.0), "sound": 16.0},
        {"room": "kitchen", "start": at("03:12"), "end": at("03:20"), "lux": rng.uniform(60, 90), "sound": 9.0, "humidity": 6.0},
    ]
    for e in events:
        for t in range(e["start"], e["end"]):
            n.people[e["room"]][t] += 1
            n.activity[e["room"]][t] = 1
            n.light[e["room"]][t] = e["lux"]
            n.extra_sound[e["room"]][t] += e["sound"]
            n.extra_humidity[e["room"]][t] += e.get("humidity", 0.0) * min(1.0, (t - e["start"] + 1) / 4)
            n.ghost[e["room"]][t] = 1
    door = at("03:33")
    n.door[door] = 1
    n.cat_walk(at("04:18"), rng)
    return [{"room": e["room"], "start": hhmm(e["start"]), "end": hhmm(e["end"])} for e in events] + [
        {"room": "hallway", "start": hhmm(door), "end": hhmm(door + 1), "note": "front door contact opened, no motion"},
        {"room": "(cat)", "start": "04:18", "note": "the cat walks through; motion only, not a presence to report"}]


def sensors(n, rng, night_label, labelled):
    rows = []
    co2 = {r: OUTDOOR_CO2 + rng.uniform(150, 300) for r in ROOMS}
    temp = {r: 20.5 + rng.uniform(-0.5, 0.5) for r in ROOMS}
    fridge_phase = rng.randint(0, 44)
    for t in range(MINUTES):
        hvac = 0.35 * math.sin(2 * math.pi * (t + 13) / 90.0)
        for r in ROOMS:
            p, a = n.people[r][t], n.activity[r][t]
            rate = {0: 0.6, 1: 1.0, 2: 1.3}[a] * 300.0 / VOLUME_M3[r]
            vent = 0.012 if r == "bedroom" else 0.03
            co2[r] += p * rate - vent * (co2[r] - OUTDOOR_CO2) + rng.gauss(0, 2.0)
            lux = n.light[r][t]
            if lux is None:
                lux = rng.uniform(0.0, 2.5)   # street light through the blinds
            light = max(0.0, lux + rng.gauss(0, 0.3 + 0.03 * lux))
            sound = 26.0 + rng.gauss(0, 1.5) + n.extra_sound[r][t]
            if p:
                sound += {0: 2.0, 1: 7.0, 2: 18.0}[a] + rng.gauss(0, 2.0)
            if r == "kitchen" and (t + fridge_phase) % 45 < 12:
                sound += 6.0 + rng.gauss(0, 0.8)  # fridge compressor cycle
            rate_pir = {0: 0.15, 1: 0.8, 2: 2.0}[a] if p else 0.01
            motion = sum(1 for _ in range(4) if rng.random() < rate_pir / 4)
            if n.ghost[r][t]:
                motion = rng.choice([0, 1, 1, 2])
            if n.cat[r][t]:
                motion += rng.choice([0, 1, 1, 2])
                sound += rng.uniform(0.5, 3.0)
            temp[r] += 0.004 * p - 0.01 * (temp[r] - 20.5 - hvac) + rng.gauss(0, 0.01)
            humidity = 45.0 + 2.0 * math.sin(t / 97.0) + n.extra_humidity[r][t] + 0.6 * p + rng.gauss(0, 0.4)
            row = {"night": night_label, "time": hhmm(t), "minute": t, "room": r, "co2": round(co2[r], 1),
                   "light": round(light, 1), "sound": round(sound, 1), "motion": motion, "temp": round(temp[r], 2),
                   "humidity": round(humidity, 1), "door": n.door[t] if r == "hallway" else 0}
            if labelled:
                row["occupied"] = 1 if p > 0 else 0
            rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--seed", type=int, default=31)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    train = []
    for i in range(7):
        night, _, _ = ordinary_night(rng)
        train += sensors(night, rng, f"2026-10-{24 + i:02d}", True)
    night, sleep, wake = ordinary_night(rng, trips=[at("01:58")])
    truth = haunt(night, rng)
    halloween = sensors(night, rng, "2026-10-31", False)
    for name, rows, fields in (("train.csv", train, FIELDS + ["occupied"]), ("halloween.csv", halloween, FIELDS)):
        with open(out / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    (out / "halloween_truth.json").write_text(json.dumps(
        {"note": "Simulator ground truth for checking the detector; the detector never reads this file.",
         "residents_asleep": [hhmm(sleep), hhmm(wake)], "resident_trip": "01:58 bedroom -> kitchen -> bedroom",
         "injected": truth}, indent=1))
    print(f"wrote {len(train)} training rows and {len(halloween)} Halloween rows to {out}")


if __name__ == "__main__":
    main()
