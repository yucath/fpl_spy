import requests
from datetime import datetime, time, timedelta
import pytz
from pathlib import Path
import subprocess
import sys
import time as time_module
from typing import Dict, List, Optional

PST = pytz.timezone('America/Los_Angeles')

def get_current_pst_time():
    """Get current time in PST"""
    return datetime.now(PST)

def get_all_gameweeks():
    """Fetch all gameweeks and their fixtures, using PST for scheduling"""
    try:
        bootstrap_url = "https://fantasy.premierleague.com/api/bootstrap-static/"
        response = requests.get(bootstrap_url)
        response.raise_for_status()
        data = response.json()
        
        gameweeks = {}
        
        for gw in data['events']:
            fixtures_url = f"https://fantasy.premierleague.com/api/fixtures/?event={gw['id']}"
            fixtures_response = requests.get(fixtures_url)
            fixtures_response.raise_for_status()
            fixtures = fixtures_response.json()
            
            if not fixtures:  # Skip gameweeks with no fixtures
                continue
                
            # Group fixtures by date in PST
            fixtures_by_date = {}
            for fixture in fixtures:
                # Convert UTC kickoff to PST
                kickoff_time = datetime.strptime(fixture['kickoff_time'], '%Y-%m-%dT%H:%M:%SZ')
                kickoff_time = pytz.UTC.localize(kickoff_time)
                kickoff_time_pst = kickoff_time.astimezone(PST)
                date_key = kickoff_time_pst.date()
                
                if date_key not in fixtures_by_date:
                    fixtures_by_date[date_key] = []
                fixtures_by_date[date_key].append(kickoff_time_pst)
            
            if not fixtures_by_date:  # Skip if no fixtures with dates
                continue
                
            # For each date, find the last game (all times in PST)
            last_game_times = {date: max(times) for date, times in fixtures_by_date.items()}
            
            gameweeks[gw['id']] = {
                'id': gw['id'],
                'name': gw['name'],
                'start_date': min(fixtures_by_date.keys()),
                'end_date': max(fixtures_by_date.keys()),
                'last_game_times': last_game_times,
                'final_game_time': max(max(times) for times in fixtures_by_date.values())
            }
            
        return gameweeks
    except Exception as e:
        print(f"Error fetching gameweeks: {e}")
        return None

def get_current_gameweek(gameweeks):
    """Determine current gameweek based on current PST time"""
    current_time = get_current_pst_time()
    current_date = current_time.date()
    
    # First check if we're in the middle of a gameweek
    for gw_id, gw in gameweeks.items():
        if gw['start_date'] <= current_date <= gw['end_date']:
            return gw_id, 'ongoing'
    
    # If not, find the next gameweek
    next_gw = None
    for gw_id, gw in gameweeks.items():
        if gw['start_date'] > current_date:
            if next_gw is None or gw['start_date'] < gameweeks[next_gw]['start_date']:
                next_gw = gw_id
    
    if next_gw:
        return next_gw, 'upcoming'
    
    return None, 'finished'

def run_analysis(gameweek: int, is_final: bool = False) -> None:
    """Run the FPL analysis script and FB sender"""
    script_path = Path(__file__).parent / 'main_new.py'
    command = [sys.executable, str(script_path), '--gw', str(gameweek)]
    if is_final:
        command.append('--final')
    
    try:
        subprocess.run(command, check=True)
        print(f"Successfully ran analysis for GW{gameweek} {'(Final)' if is_final else ''}")
        
        # Run FB sender after every analysis
        fb_script = Path(__file__).parent / 'fb_sender.py'
        subprocess.run([sys.executable, str(fb_script)], check=True)
        print("Successfully ran FB sender")
    except subprocess.CalledProcessError as e:
        print(f"Error running analysis: {e}")

def format_time(dt):
    """Format datetime in PST with weekday"""
    return dt.strftime('%A, %B %d at %I:%M %p %Z')

def main():
    print("Starting FPL Analysis Scheduler...")
    MIN_SLEEP_TIME = 300  # 5 minutes
    
    while True:
        try:
            print("\nFetching gameweek information...")
            gameweeks = get_all_gameweeks()
            if not gameweeks:
                print("No gameweeks found. Retrying in 5 minutes...")
                time_module.sleep(MIN_SLEEP_TIME)
                continue
            
            current_gw_id, status = get_current_gameweek(gameweeks)
            current_time = get_current_pst_time()
            
            if status == 'finished':
                print("All gameweeks completed. Exiting...")
                break
                
            if status == 'upcoming':
                next_gw = gameweeks[current_gw_id]
                seconds_until_start = (next_gw['start_date'] - current_time.date()).days * 86400
                first_game = min(next_gw['last_game_times'].values())
                print(f"\nSchedule for Gameweek {current_gw_id}:")
                print(f"First game: {format_time(first_game)}")
                print("\nAnalysis schedule:")
                
                # Print schedule for each gameday
                for date in sorted(next_gw['last_game_times'].keys()):
                    last_game = next_gw['last_game_times'][date]
                    analysis_time = last_game + timedelta(hours=7)
                    is_final_day = (last_game == next_gw['final_game_time'])
                    print(f"- {format_time(last_game)}: Last game of {date.strftime('%A')}")
                    print(f"  → {format_time(analysis_time)}: {'Final' if is_final_day else 'Daily'} analysis + FB sender")
                
                sleep_time = min(seconds_until_start, 36000)
                print(f"Checking again in {sleep_time//3600} hours...")
                time_module.sleep(sleep_time)
                continue
            
            # We're in an ongoing gameweek
            current_gw = gameweeks[current_gw_id]
            print(f"\nProcessing Gameweek {current_gw_id}")
            
            # Find next game day that hasn't been analyzed
            next_analysis_time = None
            is_final = False
            
            for date in sorted(current_gw['last_game_times'].keys()):
                last_game_time = current_gw['last_game_times'][date]
                analysis_time = last_game_time + timedelta(hours=7)
                
                if analysis_time > current_time:
                    next_analysis_time = analysis_time
                    is_final = (last_game_time == current_gw['final_game_time'])
                    break
            
            if not next_analysis_time:
                print("All analyses completed for current gameweek")
                time_module.sleep(MIN_SLEEP_TIME)
                continue
            
            # Wait for next analysis time
            seconds_until_analysis = (next_analysis_time - current_time).total_seconds()
            if seconds_until_analysis > 300:
                print(f"Next analysis at: {format_time(next_analysis_time)}")
                print(f"Type: {'Final' if is_final else 'Daily'} analysis")
                if is_final:
                    print("Will run FB sender after analysis")
                
                sleep_time = min(seconds_until_analysis - 300, 3600)
                print(f"Checking again in {sleep_time//60} minutes")
                time_module.sleep(sleep_time)
                continue
            
            # Time to run analysis
            run_analysis(current_gw_id, is_final)
            time_module.sleep(MIN_SLEEP_TIME)  # Brief sleep after analysis
            
        except Exception as e:
            print(f"Error occurred: {e}")
            print("Retrying in 5 minutes...")
            time_module.sleep(MIN_SLEEP_TIME)

if __name__ == "__main__":
    main()