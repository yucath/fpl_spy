"""
schedule.py — FPL analysis scheduler.

Logic:
- Fetch bootstrap-static to find which GW is current/next (1 API call).
- Fetch only THAT GW's fixtures (1 API call).
- Sleep until last_game + 7h for each game-day; flag the last game-day as --final.
- On GW38 final post, exit cleanly (run_forever.sh will NOT restart because
  we exit with code 0 only at end-of-season — all other exits are crashes).
- Fixture dates are always queried fresh, never hardcoded.
"""

import requests
from datetime import datetime, timedelta
import pytz
from pathlib import Path
import subprocess
import sys
import time as time_module

PST = pytz.timezone("America/Los_Angeles")
MIN_SLEEP = 300   # 5 min minimum between loop iterations
MAX_SLEEP = 3600  # never sleep longer than 1 hour without rechecking


def now_pst():
    return datetime.now(PST)


def fmt(dt):
    return dt.strftime("%A %b %d at %I:%M %p %Z")


def fetch_json(url: str):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def get_current_gw_info():
    """
    Return (gw_id, status, schedule) where:
      status  = 'ongoing' | 'upcoming' | 'finished'
      schedule = None if finished, else:
        {
          'id': int,
          'last_game_times': {date: last_kickoff_pst},   # one entry per game-day
          'final_game_time': datetime,                    # last kickoff of the whole GW
          'is_last_gw': bool,
        }
    """
    data = fetch_json("https://fantasy.premierleague.com/api/bootstrap-static/")
    events = data["events"]
    total_gws = len(events)

    # Find the active / next GW using FPL's own flags
    current_event = next((e for e in events if e.get("is_current")), None)
    next_event    = next((e for e in events if e.get("is_next")),    None)

    if current_event:
        gw_id  = current_event["id"]
        status = "ongoing"
    elif next_event:
        gw_id  = next_event["id"]
        status = "upcoming"
    else:
        # All GWs finished
        return None, "finished", None

    is_last_gw = (gw_id == total_gws)

    # Now fetch only this GW's fixtures
    fixtures = fetch_json(f"https://fantasy.premierleague.com/api/fixtures/?event={gw_id}")
    if not fixtures:
        return gw_id, status, None

    fixtures_by_date = {}
    for f in fixtures:
        if not f.get("kickoff_time"):
            continue
        ko = datetime.strptime(f["kickoff_time"], "%Y-%m-%dT%H:%M:%SZ")
        ko_pst = pytz.utc.localize(ko).astimezone(PST)
        d = ko_pst.date()
        fixtures_by_date.setdefault(d, []).append(ko_pst)

    if not fixtures_by_date:
        return gw_id, status, None

    last_game_times = {d: max(times) for d, times in fixtures_by_date.items()}
    final_game_time = max(last_game_times.values())

    schedule = {
        "id": gw_id,
        "last_game_times": last_game_times,
        "final_game_time": final_game_time,
        "is_last_gw": is_last_gw,
    }
    return gw_id, status, schedule


def run_analysis(gameweek: int, is_final: bool = False) -> bool:
    """Run main_new.py then fb_sender.py. Returns True on success."""
    script_path = Path(__file__).parent / "main_new.py"
    cmd = [sys.executable, str(script_path), "--gw", str(gameweek)]
    if is_final:
        cmd.append("--final")

    print(f"[{now_pst():%H:%M}] Running analysis GW{gameweek} {'(FINAL)' if is_final else '(daily)'} ...")
    try:
        subprocess.run(cmd, check=True)
        print(f"[{now_pst():%H:%M}] Analysis done. Sending to Facebook...")
        fb_path = Path(__file__).parent / "fb_sender.py"
        subprocess.run([sys.executable, str(fb_path)], check=True)
        print(f"[{now_pst():%H:%M}] Facebook send done.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[{now_pst():%H:%M}] ERROR: {e}")
        return False


def main():
    print("=" * 60)
    print("FPL Spy Scheduler — starting up")
    print("Will post after each game-day + a FINAL post at GW end.")
    print("Exits cleanly only after GW38 final post.")
    print("=" * 60)

    while True:
        try:
            print(f"\n[{now_pst():%Y-%m-%d %H:%M}] Fetching current GW info ...")
            gw_id, status, schedule = get_current_gw_info()

            if status == "finished":
                print("Season finished. All GWs done. Exiting.")
                sys.exit(0)  # clean exit — run_forever.sh exits too

            if status == "upcoming" or schedule is None:
                print(f"GW{gw_id} hasn't started yet. Checking again in 1 hour.")
                time_module.sleep(MAX_SLEEP)
                continue

            # Ongoing GW
            current_time = now_pst()
            print(f"GW{gw_id} is ongoing. Game-days: "
                  f"{', '.join(str(d) for d in sorted(schedule['last_game_times']))}")

            # Find the next scheduled analysis time
            next_analysis = None
            next_is_final = False

            for date in sorted(schedule["last_game_times"]):
                last_ko   = schedule["last_game_times"][date]
                run_at    = last_ko + timedelta(hours=7)
                is_final  = (last_ko == schedule["final_game_time"])

                if run_at > current_time:
                    next_analysis  = run_at
                    next_is_final  = is_final
                    break

            if next_analysis is None:
                # All analysis windows for this GW have passed
                print("All analysis windows for this GW have passed. Waiting for GW to roll over...")
                time_module.sleep(MAX_SLEEP)
                continue

            wait_secs = (next_analysis - current_time).total_seconds()
            print(f"Next {'FINAL ' if next_is_final else ''}analysis: {fmt(next_analysis)} "
                  f"({wait_secs/60:.0f} min from now)")

            if wait_secs > MIN_SLEEP:
                sleep_for = min(wait_secs - MIN_SLEEP, MAX_SLEEP)
                print(f"Sleeping {sleep_for/60:.0f} min, then rechecking ...")
                time_module.sleep(sleep_for)
                continue

            # Time to run
            success = run_analysis(gw_id, next_is_final)
            if success and next_is_final and schedule["is_last_gw"]:
                print("GW38 FINAL done. Season complete. Exiting.")
                sys.exit(0)

            time_module.sleep(MIN_SLEEP)

        except requests.RequestException as e:
            print(f"Network error: {e}. Retrying in 5 min...")
            time_module.sleep(MIN_SLEEP)
        except Exception as e:
            import traceback
            print(f"Unexpected error: {e}")
            traceback.print_exc()
            print("Retrying in 5 min...")
            time_module.sleep(MIN_SLEEP)


if __name__ == "__main__":
    main()
