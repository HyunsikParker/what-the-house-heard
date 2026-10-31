"""Have a local Gemma model tell the night as a ghost story, using only the detector's evidence, then check the story
against that evidence.

usage: python narrate.py EVENTS_JSON OUT_JSON [--url http://127.0.0.1:8089/v1/chat/completions] [--seed 31] [--attempts 4]

Start llama.cpp's server first, for example:
  llama-server -m gemma-4-12b-it-qat-q4_0.gguf --jinja --reasoning-budget 0 --port 8089
Nothing leaves the machine: the request goes to localhost.
"""
import argparse
from decimal import Decimal
import json
import re
import time
import urllib.request

ROOM_NAMES = {"living_room": "living room", "kitchen": "kitchen", "hallway": "hallway", "bedroom": "bedroom"}

SYSTEM = (
    "You write very short ghost stories from smart-home sensor evidence. Tell it as a story; do not copy the evidence "
    "sentences. Use only the rooms, times and readings in the evidence, and work in at least three readings with their "
    "units, using the numbers exactly as given (for example '53.5 dBA'); CO2 figures are rises, not levels. Do not "
    "invent people, names, animals, objects, smells or sounds, and do not describe light or air that the readings do "
    "not show. Never contradict the evidence. Write in the second person and the present tense, 150 to 220 words, no title. The reader is one of the "
    "two residents, lying awake in the bedroom next to the other one. After the story, add one line that starts with 'The boring explanation:' "
    "and offers a mundane cause, phrased as a guess."
)


def evidence(report):
    lines = [f"Night of {report['night']}. Two residents went to bed before midnight, and the bedroom looked occupied all "
             "night. The door sensor reports only open or closed."]
    for e in report["events"]:
        room = ROOM_NAMES.get(e["room"], e["room"])
        if e["kind"] == "explained":
            night_time = e["start"] >= "23:30" or e["start"] < "06:00"
            if night_time and e["room"] != "hallway":
                lines.append(f"- {e['start']} to {e['end']}, {room}: a resident came through the hallway and stayed (explained).")
            continue
        if "co2_change_ppm" in e:
            lines.append(
                f"- {e['start']} to {e['end']}, {room}: nobody crossed the hallway to get there, yet the room reads as "
                f"occupied. CO2 up {e['co2_change_ppm']:g} ppm. Light at most {e['light_max_lux']:g} lux. Sound up to "
                f"{e['sound_max_dba']:g} dBA. Humidity up to {e['humidity_max_pct']:g}%. {e['motion_triggers']} motion triggers.")
        else:
            lines.append(f"- {e['start']}, {room}: {e['why']}.")
    return "\n".join(lines)


def ask(url, story_prompt, seed, tries=60):
    body = json.dumps({"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": story_prompt}],
                       "temperature": 0.8, "top_p": 0.95, "seed": seed, "max_tokens": 700,
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.load(r)["choices"][0]["message"]["content"].strip()
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(2)  # the server may still be loading the model


UNITS = {"co2_change_ppm": "ppm", "light_max_lux": "lux", "sound_max_dba": "dBA", "humidity_max_pct": "%"}
# Capture the whole numeric token, including malformed punctuation, so a suffix
# such as "045.6" in "1,045.6" cannot pass as a different measurement.
READING = re.compile(r"(?<![\w.,+\-−])([+\-−]?(?:\d[\d.,eE+\-−]*|\.\d[\d.,eE+\-−]*))\s*(ppm|lux|dBA|%)(?![A-Za-z])")
NUMBER = re.compile(r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")


def reading_value(raw):
    """Parse a complete signed decimal, with optional thousands groups/exponent."""
    raw = raw.replace("−", "-")
    if not NUMBER.fullmatch(raw):
        return None
    return Decimal(raw.replace(",", ""))


def check(story, report):
    """Every clock time and every reading the story quotes must come from the evidence, with the right unit."""
    allowed_times, allowed_readings = set(), set()
    for e in report["events"]:
        h, m = map(int, e["start"].split(":"))
        for k in range(e.get("minutes", 1)):
            allowed_times.add(f"{(h + (m + k) // 60) % 24:02d}:{(m + k) % 60:02d}")
        allowed_times.add(e["end"])
        for key, unit in UNITS.items():
            if key in e:
                allowed_readings.add((Decimal(str(e[key])), unit))
    times = re.findall(r"\b\d{1,2}:\d{2}\b", story)
    bad_times = [t for t in times if t.zfill(5) not in allowed_times]
    readings = READING.findall(story)
    bad_readings = [f"{raw} {unit}" for raw, unit in readings
                    if (reading_value(raw), unit) not in allowed_readings]
    return {"times_quoted": len(times), "times_not_in_evidence": bad_times, "readings_quoted": len(readings),
            "readings_not_in_evidence": bad_readings, "ok": not bad_times and not bad_readings and len(readings) >= 3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("out")
    ap.add_argument("--url", default="http://127.0.0.1:8089/v1/chat/completions")
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--attempts", type=int, default=4)
    a = ap.parse_args()
    report = json.load(open(a.events))
    prompt = evidence(report)
    t0 = time.time()
    attempts = []
    for k in range(a.attempts):  # a story that misquotes the evidence is rewritten with the next seed
        story = ask(a.url, prompt, a.seed + k)
        attempts.append({"seed": a.seed + k, "check": check(story, report)})
        if attempts[-1]["check"]["ok"]:
            break
    result = {"evidence": prompt, "story": story, "seconds": round(time.time() - t0, 1), "check": attempts[-1]["check"],
              "attempts": attempts}
    json.dump(result, open(a.out, "w"), indent=1)
    print(story)
    print("\ncheck:", result["check"], f"({len(attempts)} attempt(s), {result['seconds']} s)")


if __name__ == "__main__":
    main()
