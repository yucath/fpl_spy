import json
import sys
import requests
import os
from datetime import datetime
import argparse
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from typing import List, Dict
import os
import numpy as np
import shutil
from collections import defaultdict
import matplotlib.colors as mcolors
from matplotlib.patches import FancyBboxPatch
from matplotlib.font_manager import FontProperties, findfont
import logging 
import pytz
from dotenv import load_dotenv
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# Set up logging to file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fpl_analysis.log'),
        logging.StreamHandler()
    ]
)

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI library not available")

# Load environment variables
load_dotenv()

local_path = os.path.dirname(os.path.realpath(__file__))

BASE_URL = "https://fantasy.premierleague.com/api/"

def fetch_data(url):
    response = requests.get(url)
    if response.status_code != 200:
        print(f"Failed to fetch data from {url}.")
        return None
    return response.json()

def fetch_live_gameweek_data(gameweek):
    """Fetch live gameweek data from the FPL API."""
    url = BASE_URL + f"event/{gameweek}/live/"
    return fetch_data(url)

def fetch_bootstrap_data():
    url = BASE_URL + "bootstrap-static/"
    return fetch_data(url)

def fetch_league_data(league_id):
    url = BASE_URL + f"leagues-classic/{league_id}/standings/"
    return fetch_data(url)

def fetch_manager_data(team_id):
    url = BASE_URL + f"entry/{team_id}/"
    return fetch_data(url)

def fetch_manager_transfers(team_id):
    url = BASE_URL + f"entry/{team_id}/transfers/"
    return fetch_data(url)

def fetch_manager_history(team_id):
    url = BASE_URL + f"entry/{team_id}/history/"
    return fetch_data(url)

def fetch_gameweek_data_for_team(team_id, gameweek):
    url = BASE_URL + f"entry/{team_id}/event/{gameweek}/picks/"
    return fetch_data(url)

def fetch_fixtures(gameweek: int = None) -> list:
    """Fetch fixtures data. If gameweek is specified, filter for that gameweek."""
    url = BASE_URL + "fixtures/"
    if gameweek:
        url += f"?event={gameweek}"
    return fetch_data(url)

def build_play_status_map(gameweek: int, players_data: List[Dict]) -> Dict[int, str]:
    """
    Map each player_id -> play status for this gameweek:
      'finished'  -> all of the player's team fixtures are done (points final)
      'playing'   -> a fixture has kicked off but isn't finished yet
      'upcoming'  -> the player's team hasn't started yet (points still 0/provisional)

    Handles double gameweeks (a team is 'playing' until ALL its fixtures finish).
    Used to avoid, e.g., flagging a "captain fail" for a captain who hasn't
    kicked off yet.
    """
    fixtures = fetch_fixtures(gameweek) or []

    team_started: Dict[int, bool] = {}
    team_all_finished: Dict[int, bool] = {}
    for fx in fixtures:
        started = bool(fx.get('started'))
        finished = bool(fx.get('finished') or fx.get('finished_provisional'))
        for team in (fx.get('team_h'), fx.get('team_a')):
            if team is None:
                continue
            team_started[team] = team_started.get(team, False) or started
            # all_finished stays True only if every fixture for the team is finished
            prev = team_all_finished.get(team, True)
            team_all_finished[team] = prev and finished

    status_map: Dict[int, str] = {}
    for p in players_data:
        team = p.get('team')
        if team not in team_started:
            status_map[p['id']] = 'upcoming'
        elif team_all_finished.get(team, False):
            status_map[p['id']] = 'finished'
        elif team_started.get(team, False):
            status_map[p['id']] = 'playing'
        else:
            status_map[p['id']] = 'upcoming'
    return status_map


def get_gameweek_status(gameweek: int) -> Dict:
    """
    Get the status of a gameweek including fixtures finished/remaining.
    Returns dict with is_finished, fixtures_finished, fixtures_remaining, total_fixtures.
    """
    try:
        # Get bootstrap data for gameweek info
        bootstrap = fetch_bootstrap_data()
        events = bootstrap.get('events', [])
        
        # Find current gameweek event
        gw_event = next((e for e in events if e['id'] == gameweek), None)
        
        # Get fixtures for this gameweek
        fixtures = fetch_fixtures(gameweek) or []
        
        total_fixtures = len(fixtures)
        finished_fixtures = sum(1 for f in fixtures if f.get('finished', False))
        started_fixtures = sum(1 for f in fixtures if f.get('started', False))
        remaining_fixtures = total_fixtures - finished_fixtures
        in_progress = started_fixtures - finished_fixtures
        not_started_fixtures = total_fixtures - started_fixtures  # truly not yet kicked off

        # Determine gameweek status
        is_finished = gw_event.get('finished', False) if gw_event else (finished_fixtures == total_fixtures)
        is_started = gw_event.get('data_checked', False) if gw_event else (started_fixtures > 0)

        # First and last kickoff times for day-count context
        kickoff_times = []
        for f in fixtures:
            ko = f.get('kickoff_time')
            if ko:
                try:
                    kickoff_times.append(datetime.strptime(ko, '%Y-%m-%dT%H:%M:%SZ'))
                except Exception:
                    pass
        first_kickoff = min(kickoff_times) if kickoff_times else None
        last_kickoff = max(kickoff_times) if kickoff_times else None

        return {
            'is_finished': is_finished,
            'is_started': is_started,
            'total_fixtures': total_fixtures,
            'fixtures_finished': finished_fixtures,
            'fixtures_remaining': remaining_fixtures,
            'fixtures_not_started': not_started_fixtures,
            'fixtures_in_progress': in_progress,
            'deadline_time': gw_event.get('deadline_time', '') if gw_event else '',
            'gw_name': gw_event.get('name', f'Gameweek {gameweek}') if gw_event else f'Gameweek {gameweek}',
            'first_kickoff': first_kickoff,
            'last_kickoff': last_kickoff,
        }
    except Exception as e:
        logger.error(f"Error getting gameweek status: {e}")
        return {
            'is_finished': False,
            'is_started': True,
            'total_fixtures': 10,
            'fixtures_finished': 0,
            'fixtures_remaining': 10,
            'fixtures_not_started': 10,
            'fixtures_in_progress': 0,
            'deadline_time': '',
            'gw_name': f'Gameweek {gameweek}',
            'first_kickoff': None,
            'last_kickoff': None,
        }

def retrieve_mini_league_data(league_id, gameweek):
    bootstrap_data = fetch_bootstrap_data()
    league_data = fetch_league_data(league_id)
    
    # Fetch live data for the gameweek
    live_data = fetch_live_gameweek_data(gameweek)
    
    # Create player points mapping from live data
    player_id_to_live_points = {}
    if live_data and 'elements' in live_data:
        for element in live_data['elements']:
            player_id_to_live_points[element['id']] = element['stats']['total_points']
    
    for entry in league_data['standings']['results']:
        team_id = entry['entry']
        
        entry['manager_details'] = fetch_manager_data(team_id)
        entry['transfers'] = fetch_manager_transfers(team_id)
        entry['history'] = fetch_manager_history(team_id)
        
        entry['gameweek_data'] = {}
        gw = str(gameweek)
        entry['gameweek_data'][gw] = fetch_gameweek_data_for_team(team_id, gw)
        
        # Calculate live points for current gameweek and update event_total
        live_points = calculate_live_points_for_team(team_id, gameweek, live_data, player_id_to_live_points)
        entry['event_total'] = live_points  # Override with live points
    
    return league_data

def calculate_live_points_for_team(team_id, gameweek, live_data, player_id_to_points):
    """Calculate live points for a specific team using live API data."""
    picks_data = fetch_gameweek_data_for_team(team_id, gameweek)
    if not picks_data or 'picks' not in picks_data:
        return 0
    
    total_points = 0
    transfer_cost = 0
    
    # Get transfer cost (only if not using Free Hit chip)
    is_free_hit = picks_data.get('active_chip') == 'freehit'
    if not is_free_hit:
        # Get transfers for this gameweek
        transfers = fetch_manager_transfers(team_id)
        gw_transfers = [t for t in transfers if t['event'] == gameweek]
        transfer_cost = len(gw_transfers) * 4 if len(gw_transfers) > 2 else 0
    
    # Calculate points from starting XI only
    for pick in picks_data['picks']:
        if pick['position'] <= 11:  # Starting XI only
            player_points = player_id_to_points.get(pick['element'], 0)
            multiplied_points = player_points * pick['multiplier']
            total_points += multiplied_points
    
    return total_points - transfer_cost

def save_to_json(data, filename):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

def sanitize_message_for_fb(message: str) -> str:
    """
    Sanitize message for Facebook Messenger.

    Emojis (including non-BMP code points) are now preserved: FacebookManager
    types via the Chrome DevTools Protocol's Input.insertText, which accepts
    arbitrary Unicode. We only strip markdown syntax (Messenger doesn't render
    it) and tidy excessive whitespace / blank lines.
    """
    import re

    sanitized = re.sub(r'\*\*(.+?)\*\*', r'\1', message)  # **bold** -> bold
    sanitized = re.sub(r'\*(.+?)\*', r'\1', sanitized)    # *italic* -> italic
    sanitized = re.sub(r'__(.+?)__', r'\1', sanitized)    # __bold__ -> bold
    sanitized = re.sub(r'_(.+?)_', r'\1', sanitized)      # _italic_ -> italic

    sanitized = re.sub(r'^#{1,6}\s+', '', sanitized, flags=re.MULTILINE)

    sanitized = re.sub(r'[ \t]{2,}', ' ', sanitized)
    sanitized = re.sub(r'\n{3,}', '\n\n', sanitized)

    return sanitized.strip()

def calculate_gw_average(mini_league_data, gw):
    """Calculate average NET points for a gameweek (gross points - transfer costs)."""
    total_points = 0
    count = 0
    for manager in mini_league_data['standings']['results']:
        if len(manager['history']['current']) >= gw:
            gw_data = manager['history']['current'][gw - 1]
            gross_pts = gw_data['points']
            transfer_cost = gw_data.get('event_transfers_cost', 0)
            total_points += (gross_pts - transfer_cost)  # NET points
            count += 1
    
    return total_points / count if count != 0 else 0

def create_plots_directory(create_new = False):
    """Create a directory for storing plots if it doesn't exist."""
    plots_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "plots")
    if create_new:
        if os.path.exists(plots_dir):
            shutil.rmtree(plots_dir)
    os.makedirs(plots_dir, exist_ok=True)
    return plots_dir

def plot_league_standings(mini_league_data: Dict, gameweek: int) -> None:
    """Plot the current league standings as a horizontal bar chart."""
    plt.figure(figsize=(12, 6))
    
    standings = mini_league_data['standings']['results']
    teams = [team['entry_name'] for team in standings]
    points = [team['total'] for team in standings]
    
    # Create horizontal bar chart
    plt.barh(teams, points, color='skyblue')
    plt.xlabel('Total Points')
    plt.ylabel('Team Name')
    plt.title(f'League Standings - Gameweek {gameweek}')
    
    # Add value labels on the bars
    for i, v in enumerate(points):
        plt.text(v, i, str(v), va='center', fontweight='bold')
    
    plt.tight_layout()
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'league_standings_gw{gameweek}.png'))
    plt.close()

def plot_weekly_points(mini_league_data: Dict) -> None:
    """Plot the weekly points for each manager in the league."""
    # Set style for better visibility
    try:
        plt.style.use('seaborn-v0_8-darkgrid')  # 'seaborn' was removed in matplotlib>=3.6
    except OSError:
        pass
    plt.figure(figsize=(15, 10))
    
    # Create more distinctive color palette
    colors = plt.cm.Dark2(np.linspace(0, 1, len(mini_league_data['standings']['results'])))
    
    # Plot weekly points for each manager
    for idx, manager in enumerate(mini_league_data['standings']['results']):
        manager_name = manager['entry_name']
        history = manager['history']['current']
        gameweeks = [entry['event'] for entry in history]
        points = [entry['points'] - entry.get('event_transfers_cost', 0) for entry in history]  # NET points
        
        # Plot points with lines and markers
        plt.plot(gameweeks, points, '-o', label=manager_name,
                color=colors[idx], linewidth=2, markersize=6)
        
        # Add point labels for the latest gameweek
        if points:
            plt.annotate(f'{points[-1]}', 
                        xy=(gameweeks[-1], points[-1]),
                        xytext=(5, 0), textcoords='offset points',
                        fontsize=10, fontweight='bold',
                        color=colors[idx])
    
    plt.xlabel('Gameweek', fontsize=12, fontweight='bold')
    plt.ylabel('Weekly Points', fontsize=12, fontweight='bold')
    plt.title('Weekly Performance Analysis', 
              fontsize=14, fontweight='bold', pad=20)
    
    # Set integer ticks for gameweeks
    plt.xticks(range(1, max(gameweeks) + 1))
    
    # Add grid for better readability
    plt.grid(True, alpha=0.2)
    
    # Create legend with two columns at the bottom center
    plt.legend(loc='lower center', 
              bbox_to_anchor=(0.5, -0.35),  # Moved lower
              ncol=2,
              fontsize=12, 
              frameon=True,
              fancybox=True,
              shadow=True)
    
    # Adjust layout to make room for the legend
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.25)  # Increased bottom margin
    
    # Save the figure
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, 'weekly_performance.png'), 
                dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def plot_number_of_weekly_winners(mini_league_data: Dict,num) -> None:
    """Plot number of weekly wins for each manager with details of winning gameweeks."""
    plt.figure(figsize=(12, 8))
    
    # Extract all managers' weekly points
    weekly_winners = {}  # Will store fractional wins
    weekly_wins_detail = {}  # Will store which gameweeks they won (for legend)
    all_gameweeks = set()
    
    # First, gather all gameweeks and points for each manager
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        weekly_winners[manager_name] = 0.0  # Start with 0 fractional wins
        weekly_wins_detail[manager_name] = []  # Track winning gameweeks
        
        for gw_data in manager['history']['current']:
            all_gameweeks.add(gw_data['event'])
    
    latest_gameweek = max(all_gameweeks)  # Get the latest gameweek
    
    # For each gameweek, find the winner(s) and assign fractional wins
    for gw in sorted(all_gameweeks):
        gw_scores = []
        for manager in mini_league_data['standings']['results']:
            manager_name = manager['entry_name']
            gw_data = next((x for x in manager['history']['current'] if x['event'] == gw), None)
            if gw_data:
                net_pts = gw_data['points'] - gw_data.get('event_transfers_cost', 0)
                gw_scores.append((manager_name, net_pts))
        
        if gw_scores:
            max_score = max(score[1] for score in gw_scores)
            winners = [name for name, score in gw_scores if score == max_score]
            num_winners = len(winners)
            
            # Each winner gets 1/num_winners wins (0.5 for 2, 1/3 for 3, etc.)
            win_value = 1.0 / num_winners
            
            for winner in winners:
                weekly_winners[winner] += win_value
                weekly_wins_detail[winner].append(gw)
    
    # Prepare data for plotting
    managers = list(weekly_winners.keys())
    win_counts = [weekly_winners[manager] for manager in managers]
    
    # Create bar plot
    colors = plt.cm.Dark2(np.linspace(0, 1, len(managers)))
    bars = plt.bar(managers, win_counts, color=colors)
    
    # Customize the plot
    plt.title(f'Number of Weekly Wins per Manager (through GW{latest_gameweek})\n(Joint winners count as fractional wins)', 
             fontsize=14, fontweight='bold', pad=20)
    plt.xlabel('Managers', fontsize=12, fontweight='bold')
    plt.ylabel('Number of Weekly Wins (fractional for ties)', fontsize=12, fontweight='bold')
    
    # Rotate x-axis labels for better readability
    plt.xticks(rotation=45, ha='right')
    
    # Add value labels on top of each bar (show fractional wins properly)
    for bar in bars:
        height = bar.get_height()
        # Format: show as fraction if not whole number, otherwise as integer
        if height == int(height):
            label = f'{int(height)}'
        else:
            # Show as fraction (e.g., 0.5, 0.33, etc.)
            label = f'{height:.2f}'.rstrip('0').rstrip('.')
        plt.text(bar.get_x() + bar.get_width()/2., height,
                label,
                ha='center', va='bottom', fontsize=12, fontweight='bold')
    
    # Create legend entries with winning gameweeks
    legend_labels = []
    for manager in managers:
        winning_gws = weekly_wins_detail[manager]
        if winning_gws:
            gw_str = ', '.join(f'GW{gw}' for gw in sorted(winning_gws))
            legend_labels.append(f'{manager}\nWinning weeks: {gw_str}')
        else:
            legend_labels.append(f'{manager}\nNo weekly wins')
    
    # Add legend at the bottom
    plt.legend(bars, legend_labels,
              loc='upper center',
              bbox_to_anchor=(0.5, -0.25),
              ncol=2,
              fontsize=10,
              frameon=True,
              fancybox=True,
              shadow=True)
    
    # Adjust layout
    plt.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.3)  # Make room for legend
    
    # Save the plot
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'{num}_weekly_winners.png'), 
                dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def plot_gameweek_points(mini_league_data: Dict, gameweek: int,num) -> None:
    """Plot the points for each manager in the gameweek in descending order."""
    plt.figure(figsize=(12, 8))
    
    # Collect points data for the gameweek
    manager_points = []
    for manager in mini_league_data['standings']['results']:
        gw_data = next((gw for gw in manager['history']['current'] if gw['event'] == gameweek), None)
        if gw_data:
            net_pts = gw_data['points'] - gw_data.get('event_transfers_cost', 0)  # NET points
            manager_points.append({
                'manager': manager['entry_name'],
                'points': net_pts
            })
    
    # Sort by points in descending order
    manager_points.sort(key=lambda x: x['points'], reverse=True)
    
    # Prepare data for plotting
    managers = [data['manager'] for data in manager_points]
    points = [data['points'] for data in manager_points]
    
    # Create bar plot with distinctive colors
    colors = plt.cm.Dark2(np.linspace(0, 1, len(managers)))
    bars = plt.bar(managers, points, color=colors)
    
    # Calculate average points for reference line
    avg_points = sum(points) / len(points)
    plt.axhline(y=avg_points, color='red', linestyle='--', alpha=0.5)
    plt.text(len(managers)-1, avg_points, f'Average: {avg_points:.1f}', 
             va='bottom', ha='right', color='red', fontweight='bold')
    
    # Customize the plot
    plt.title(f'Gameweek {gameweek} Performance', fontsize=14, fontweight='bold', pad=20)
    plt.xlabel('Managers', fontsize=12, fontweight='bold')
    plt.ylabel('Points', fontsize=12, fontweight='bold')
    
    # Rotate x-axis labels for better readability
    plt.xticks(rotation=45, ha='right')
    
    # Add value labels on top of each bar
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(height)}',
                ha='center', va='bottom', fontsize=12, fontweight='bold')
    
    # Add grid for better readability
    plt.grid(axis='y', alpha=0.3)
    
    # Adjust layout
    plt.tight_layout()
    
    # Save the plot
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'{num}_gameweek_{gameweek}_points.png'), 
                dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def plot_captain_choices(mini_league_data: Dict, gameweek: int, player_id_to_name: Dict, player_id_to_points: Dict,num) -> None:
    """Plot captain choices and their points for the gameweek."""
    # Set global font sizes
    plt.rcParams.update({
        'font.size': 20,
        'font.weight': 'bold'
    })
    
    plt.figure(figsize=(16, 12))  # Even larger figure size for better readability
    
    captain_data = []
    for manager in mini_league_data['standings']['results']:
        gw_data = manager['gameweek_data'].get(str(gameweek), {})
        picks = gw_data.get('picks', [])
        captain_id = next((pick['element'] for pick in picks if pick['is_captain']), None)
        if captain_id:
            points = next((pick['multiplier'] * player_id_to_points.get(pick['element'], 0) 
                          for pick in picks if pick['is_captain']), 0)
            captain_data.append({
                'manager': manager['entry_name'],
                'captain': player_id_to_name.get(captain_id, 'Unknown'),
                'points': points
            })
    
    df = pd.DataFrame(captain_data)
    
    # Group by captain and create a dictionary of managers and points for each captain
    captain_groups = df.groupby('captain').agg({
        'manager': list,
        'points': list
    }).reset_index()
    
    captain_groups['count'] = captain_groups['manager'].apply(len)
    captain_groups['total_points'] = captain_groups['points'].apply(sum)
    captain_groups['avg_points'] = captain_groups['points'].apply(lambda x: sum(x) / len(x))
    
    # Create color map for distinct colors
    colors = plt.cm.Set3(np.linspace(0, 1, len(captain_groups)))
    
    # Create pie chart with larger font sizes
    wedges, texts, autotexts = plt.pie(
        captain_groups['count'], 
        labels=captain_groups['captain'],
        colors=colors,
        autopct=lambda pct: f'{pct:.1f}%',
        startangle=90,
        textprops={'fontsize': 16, 'fontweight': 'bold'}  # Larger font for all text
    )
    
    # Make percentage labels bold and larger
    for autotext in autotexts:
        autotext.set_fontsize(14)
        autotext.set_fontweight('bold')
    
    # Create legend entries with points information
    legend_entries = []
    for _, row in captain_groups.iterrows():
        entry = f"{row['captain']} (Avg: {row['avg_points']:.1f} pts):\n"
        for manager, pt in zip(row['manager'], row['points']):
            entry += f"• {manager} ({pt} pts)\n"
        legend_entries.append(entry)
    
    # Add legend with increased font size
    plt.legend(
        wedges,
        legend_entries,
        title="Captains and Managers",
        loc="center left",
        bbox_to_anchor=(1, 0.5),
        bbox_transform=plt.gcf().transFigure,
        fontsize=14,  # Increased font size for legend text
        title_fontsize=16,  # Increased font size for legend title
    )
    
    plt.title(f'Captain Choices Distribution - Gameweek {gameweek}', 
              fontsize=20,  # Larger title font
              pad=20,       # Add padding above title
              fontweight='bold')  # Make title bold
    plt.axis('equal')
    
    # Adjust layout to prevent legend cutoff
    plt.tight_layout()
    plt.subplots_adjust(right=0.70)  # Increased right margin for larger legend
    
    # Save the figure with higher resolution
    figname = f'{num}_captain_choices_gw{gameweek}.png'
    figname = os.path.join(create_plots_directory(), figname)
    plt.savefig(figname, bbox_inches='tight', dpi=300, facecolor='white')
    plt.close()

def plot_formation_distribution(mini_league_data: Dict, gameweek: int, player_id_to_position: Dict) -> None:
    """Plot the distribution of formations used in the gameweek."""
    formations = []
    for manager in mini_league_data['standings']['results']:
        gw_data = manager['gameweek_data'].get(str(gameweek), {})
        picks = gw_data.get('picks', [])
        
        # Calculate formation for starting 11
        starting_players = [pick for pick in picks if pick['position'] <= 11]
        formation = "{}-{}-{}".format(
            sum(1 for pick in starting_players if player_id_to_position[pick['element']] == 2),
            sum(1 for pick in starting_players if player_id_to_position[pick['element']] == 3),
            sum(1 for pick in starting_players if player_id_to_position[pick['element']] == 4)
        )
        formations.append(formation)
    
    # Create formation distribution plot
    plt.figure(figsize=(10, 6))
    formation_counts = pd.Series(formations).value_counts()
    formation_counts.plot(kind='bar')
    plt.title(f'Formation Distribution - Gameweek {gameweek}')
    plt.xlabel('Formation')
    plt.ylabel('Number of Teams')
    plt.xticks(rotation=45)
    
    # Add value labels on the bars
    for i, v in enumerate(formation_counts):
        plt.text(i, v, str(v), ha='center', va='bottom')
    
    plt.tight_layout()
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'formation_distribution_gw{gameweek}.png'))
    plt.close()

def plot_performance_vs_average(mini_league_data: Dict, gameweek: int) -> None:
    """Plot each manager's performance versus the league average."""
    avg_points = calculate_gw_average(mini_league_data, gameweek)
    
    performances = []
    for manager in mini_league_data['standings']['results']:
        gw_data = manager['gameweek_data'].get(str(gameweek), {})
        entry_history = gw_data.get('entry_history', {})
        gross_points = entry_history.get('points', 0)  # API returns GROSS points
        transfer_cost = entry_history.get('event_transfers_cost', 0)
        net_points = gross_points - transfer_cost  # Calculate NET after hits
        performances.append({
            'manager': manager['entry_name'],
            'points': net_points,
            'vs_average': net_points - avg_points
        })
    
    df = pd.DataFrame(performances)
    
    plt.figure(figsize=(12, 6))
    colors = ['green' if x > 0 else 'red' for x in df['vs_average']]
    plt.bar(df['manager'], df['vs_average'], color=colors)
    plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    plt.title(f'Performance vs League Average - Gameweek {gameweek}')
    plt.xlabel('Manager')
    plt.ylabel('Points vs Average')
    plt.xticks(rotation=45)
    
    # Add value labels on the bars
    for i, v in enumerate(df['vs_average']):
        plt.text(i, v, f'{v:+.1f}', ha='center', va='bottom' if v > 0 else 'top')
    
    plt.tight_layout()
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'performance_vs_average_gw{gameweek}.png'))
    plt.close()

def create_all_points_heatmap(mini_league_data: Dict,num) -> None:
    """Create a heatmap showing points distribution for each manager in all gameweeks."""
    # Extract points data for all gameweeks
    all_points = []
    manager_names = []
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        manager_names.append(manager_name)
        points = [gw['points'] - gw.get('event_transfers_cost', 0) for gw in manager['history']['current']]  # NET
        all_points.append(points)
    
    # Create a DataFrame with points data
    df = pd.DataFrame(all_points)
    
    # Set up the plot with increased width for manager names
    plt.figure(figsize=(15, 8))
    
    # Create the heatmap
    ax = sns.heatmap(df, 
                     cmap='coolwarm', 
                     cbar_kws={'label': 'Points'}, 
                     linewidths=0.5,
                     annot=True,  # Add point values in cells
                     fmt='d',     # Format as integers
                     annot_kws={'size': 8})  # Adjust annotation size
    
    # Customize the plot
    plt.title('Points Distribution by Gameweek', fontsize=14, fontweight='bold', pad=20)
    plt.xlabel('Gameweek', fontsize=12, fontweight='bold')
    plt.ylabel('Managers', fontsize=12, fontweight='bold')
    
    # Set x-axis labels (gameweeks)
    plt.xticks(np.arange(df.shape[1]) + 0.5, 
               [f'GW{i+1}' for i in range(df.shape[1])], 
               rotation=0)
    
    # Set y-axis labels (manager names) horizontally
    ax.set_yticks(np.arange(len(manager_names)) + 0.5)
    ax.set_yticklabels(manager_names, rotation=0, ha='right')
    
    # Adjust layout to prevent label cutoff
    plt.tight_layout()
    
    # Save the figure
    figname = os.path.join(create_plots_directory(), f'{num}_points_heatmap.png')
    plt.savefig(figname, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def calculate_performance_metrics(points_history: List[int]) -> Dict:
    """Calculate various performance metrics from points history."""
    if not points_history:
        return {
            'trend': 0,
            'recent_form': 0,
            'volatility': 0
        }
    
    # Calculate trend (using last 5 gameweeks if available)
    window_size = min(5, len(points_history))
    recent_points = points_history[-window_size:]
    
    # Calculate trend using linear regression
    x = np.array(range(window_size))
    y = np.array(recent_points)
    trend = np.polyfit(x, y, 1)[0]
    
    # Calculate recent form (average of last 3 gameweeks)
    recent_form = np.mean(points_history[-3:]) if len(points_history) >= 3 else np.mean(points_history)
    
    # Calculate volatility (standard deviation)
    volatility = np.std(points_history)
    
    return {
        'trend': trend,
        'recent_form': recent_form,
        'volatility': volatility
    }

def plot_performance_timeline(mini_league_data: Dict, num: int) -> None:
    """Create a timeline visualization of managers' performance with normalized scores (0-1)."""
    plt.figure(figsize=(15, 10))
    
    # Get current league standings
    current_standings = sorted(mini_league_data['standings']['results'], 
                             key=lambda x: x['rank'])
    
    # Create mapping of current league positions
    league_positions = {team['entry_name']: pos+1 
                       for pos, team in enumerate(current_standings)}
    
    # Collect and process weekly data
    manager_data = []
    weekly_points = defaultdict(list)  # Store points by gameweek
    
    for manager in mini_league_data['standings']['results']:
        points = [gw['points'] - gw.get('event_transfers_cost', 0) for gw in manager['history']['current']]  # NET
        
        # Store points by gameweek for normalization
        for gw, pts in enumerate(points):
            weekly_points[gw].append(pts)
            
        manager_data.append({
            'name': manager['entry_name'],
            'points': points,
            'metrics': calculate_performance_metrics(points),
            'league_pos': league_positions[manager['entry_name']]
        })
    
    # Sort managers by league position (bottom to top)
    manager_data.sort(key=lambda x: x['league_pos'], reverse=True)
    
    # Create visualization
    bar_height = 0.8
    cmap = plt.cm.viridis
    
    for idx, manager in enumerate(manager_data):
        normalized_points = []
        for gw, points in enumerate(manager['points']):
            gw_points = weekly_points[gw]
            gw_max = max(gw_points)
            gw_min = min(gw_points)
            if gw_max == gw_min:
                norm_value = 0.5  # If all scores are same, put in middle
            else:
                norm_value = (points - gw_min) / (gw_max - gw_min)
            normalized_points.append(norm_value)
        
        weeks = range(1, len(normalized_points) + 1)
        
        # Create gradient-colored segments
        plt.barh(y=[idx] * len(weeks),
                width=[bar_height] * len(weeks),
                left=[x-1 for x in weeks],
                height=bar_height,
                color=[cmap(p) for p in normalized_points])
        
        # Add manager name, league position and metrics
        metrics = manager['metrics']
        trend_arrow = "↑" if metrics['trend'] > 0 else "↓" if metrics['trend'] < 0 else "→"
        label = f"{manager['league_pos']}. {manager['name']} {trend_arrow}"
        plt.text(-0.5, idx, label,
                ha='right', va='center',
                fontsize=10, fontweight='bold')
    
    plt.title('Weekly Performance Rankings (0=Bottom of League, 1=Top of League)',
             fontsize=14, fontweight='bold', pad=20)
    plt.xlabel('Gameweek', fontsize=12, fontweight='bold')
    
    # Add colorbar with 0-1 scale
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=1))
    cbar = plt.colorbar(sm)
    cbar.set_label('Relative Performance (0=Bottom, 1=Top)', fontsize=10)
    
    # Customize axes
    plt.yticks([])
    plt.grid(True, axis='x', alpha=0.3)
    
    plt.tight_layout()
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'{num}_performance_timeline.png'),
                dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def calculate_interesting_stats(mini_league_data: Dict, player_id_to_name: Dict, player_id_to_points: Dict) -> Dict:
    """Calculate various interesting statistics about the league."""
    stats = {}
    
    # Track rankings for MVP calculation
    all_gameweeks = set()
    gameweek_scores = defaultdict(list)
    top_3_counts = defaultdict(int)
    bottom_3_counts = defaultdict(int)
    
    # Initialize weekly score tracking
    min_weekly_score = float('inf')
    min_score_manager = ''
    min_score_gameweek = 0
    max_weekly_score = 0
    max_score_manager = ''
    max_score_gameweek = 0
    
    # Track additional stats
    bench_points = defaultdict(int)
    transfer_hits = defaultdict(int)
    manager_scores = defaultdict(list)
    
    # Player tracking
    player_ownership = defaultdict(int)      # How many teams own each player
    player_points_dict = defaultdict(int)    # Points for each player
    player_teams = defaultdict(set)          # Which teams own each player
    player_starts = defaultdict(int)         # How many teams started each player
    captain_picks = defaultdict(int)         # How many times captained
    
    total_managers = len(mini_league_data['standings']['results'])
    latest_gw = max(gw_data['event'] for manager in mini_league_data['standings']['results'] 
                    for gw_data in manager['history']['current'])
    
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        
        # Process gameweek history
        for gw_data in manager['history']['current']:
            all_gameweeks.add(gw_data['event'])
            gross_score = gw_data['points']
            bench_score = gw_data.get('points_on_bench', 0)
            transfer_cost = gw_data.get('event_transfers_cost', 0)
            net_score = gross_score - transfer_cost  # NET points
            
            gameweek_scores[gw_data['event']].append({
                'manager': manager_name,
                'points': net_score  # Use NET points
            })
            
            manager_scores[manager_name].append(net_score)  # Use NET score
            bench_points[manager_name] += bench_score
            transfer_hits[manager_name] += transfer_cost
            
            if net_score < min_weekly_score:
                min_weekly_score = net_score
                min_score_manager = manager_name
                min_score_gameweek = gw_data['event']
            
            if net_score > max_weekly_score:
                max_weekly_score = net_score
                max_score_manager = manager_name
                max_score_gameweek = gw_data['event']
        
        # Process latest gameweek squad
        gw_data = manager['gameweek_data'].get(str(latest_gw), {})
        picks = gw_data.get('picks', [])
        
        for pick in picks:
            player_id = pick['element']
            
            # Track ownership and points
            player_ownership[player_id] += 1
            player_points_dict[player_id] = player_id_to_points.get(player_id, 0)
            player_teams[player_id].add(manager_name)
            
            # Track starting vs bench
            if pick['position'] <= 11:
                player_starts[player_id] += 1
                
            # Track captain picks
            if pick.get('is_captain', False):
                captain_picks[player_id] += 1
    
    # Calculate rankings
    for gw in all_gameweeks:
        scores = gameweek_scores[gw]
        sorted_scores = sorted(scores, key=lambda x: x['points'], reverse=True)
        
        # Count top 3 finishes
        for i, score in enumerate(sorted_scores[:3]):
            top_3_counts[score['manager']] += 1
        
        # Count bottom 3 finishes
        for i, score in enumerate(sorted_scores[-3:]):
            bottom_3_counts[score['manager']] += 1    
    # Calculate consistency scores
    consistency_scores = {
        manager: np.std(scores) 
        for manager, scores in manager_scores.items()
    }
    most_consistent = min(consistency_scores.items(), key=lambda x: x[1])
    least_consistent = max(consistency_scores.items(), key=lambda x: x[1])
    
    # Get top performers in different categories
    mvps = sorted(top_3_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    bananas = sorted(bottom_3_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    bench_masters = sorted(bench_points.items(), key=lambda x: x[1], reverse=True)[:3]
    transfer_kings = sorted(transfer_hits.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # Calculate player-related statistics
    most_owned = sorted([(pid, count) for pid, count in player_ownership.items()],
                       key=lambda x: x[1], reverse=True)[:5]
    
    highest_scoring = sorted([(pid, player_points_dict[pid]) for pid in player_ownership.keys()],
                           key=lambda x: x[1], reverse=True)[:5]
    
    differentials = sorted([(pid, player_points_dict[pid]) 
                          for pid in player_ownership.keys()
                          if player_ownership[pid] <= total_managers/3 and player_points_dict[pid] > 0],
                         key=lambda x: x[1], reverse=True)[:5]
    
    most_captained = sorted([(pid, count) for pid, count in captain_picks.items()],
                          key=lambda x: x[1], reverse=True)[:5]
    
    # Compile all stats
    stats.update({
        'highest_weekly_score': {
            'score': max_weekly_score,
            'manager': max_score_manager,
            'gameweek': max_score_gameweek
        },
        'lowest_weekly_score': {
            'score': min_weekly_score,
            'manager': min_score_manager,
            'gameweek': min_score_gameweek
        },
        'consistency': {
            'most_consistent': {
                'manager': most_consistent[0],
                'std_dev': most_consistent[1]
            },
            'least_consistent': {
                'manager': least_consistent[0],
                'std_dev': least_consistent[1]
            }
        },
        'mvps': [{'manager': m, 'top3_count': c} for m, c in mvps],
        'banana_awards': [{'manager': m, 'bottom3_count': c} for m, c in bananas],
        'bench_masters': [{'manager': m, 'bench_points': p} for m, p in bench_masters],
        'transfer_kings': [{'manager': m, 'transfer_hits': h} for m, h in transfer_kings],
        'player_stats': {
            'most_owned': [{
                'name': player_id_to_name[pid],
                'count': count,
                'ownership_pct': round(count/total_managers * 100, 1),
                'points': player_points_dict[pid]
            } for pid, count in most_owned],
            'highest_scoring': [{
                'name': player_id_to_name[pid],
                'points': pts,
                'ownership': player_ownership[pid],
                'ownership_pct': round(player_ownership[pid]/total_managers * 100, 1)
            } for pid, pts in highest_scoring],
            'differentials': [{
                'name': player_id_to_name[pid],
                'points': pts,
                'ownership': player_ownership[pid],
                'ownership_pct': round(player_ownership[pid]/total_managers * 100, 1)
            } for pid, pts in differentials],
            'most_captained': [{
                'name': player_id_to_name[pid],
                'captain_count': count,
                'captain_pct': round(count/total_managers * 100, 1),
                'points': player_points_dict[pid]
            } for pid, count in most_captained]
        }
    })
    
    return stats

def calculate_weekly_fun_facts(mini_league_data: Dict, gameweek: int, player_id_to_name: Dict, player_id_to_points: Dict, play_status: Dict = None) -> Dict:
    """Calculate fun weekly facts and 'burns' for the current gameweek.

    play_status (optional): {player_id: 'finished'|'playing'|'upcoming'}. When
    provided, results that depend on a player having actually played (captain
    fail, bench hero, differential) only trigger once that player has finished,
    so we don't call a "fail" on someone who hasn't kicked off yet.
    """
    fun_facts = {}

    def _finished(pid):
        # Without status info, assume finished (backwards compatible).
        return play_status is None or play_status.get(pid) == 'finished'
    
    # Track rank movements
    rank_movements = []
    captain_fails = []
    bench_heroes = []
    differential_heroes = []
    
    total_managers = len(mini_league_data['standings']['results'])
    
    # Calculate previous gameweek rankings based on total points (excluding current GW)
    prev_gw_standings = []
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        current_total = manager.get('total', 0)
        current_gw_points = 0
        
        # Get current GW points (NET after hits)
        gw_data = manager['gameweek_data'].get(str(gameweek), {})
        entry_history = gw_data.get('entry_history', {})
        gross_points = entry_history.get('points', 0)  # API returns GROSS
        transfer_cost = entry_history.get('event_transfers_cost', 0)
        current_gw_points = gross_points - transfer_cost  # NET points
        
        # Previous total = current total - current GW NET points
        prev_total = current_total - current_gw_points
        prev_gw_standings.append({
            'manager': manager_name,
            'total': prev_total
        })
    
    # Sort by previous total to get previous ranks
    prev_gw_standings.sort(key=lambda x: x['total'], reverse=True)
    prev_ranks = {item['manager']: idx + 1 for idx, item in enumerate(prev_gw_standings)}
    
    # Calculate rank changes
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        current_rank = manager.get('rank', 0)
        prev_rank = prev_ranks.get(manager_name, current_rank)
        
        # Calculate rank change (positive = moved up, negative = moved down)
        if current_rank > 0 and prev_rank > 0:
            rank_change = prev_rank - current_rank
            rank_movements.append({
                'manager': manager_name,
                'change': rank_change,
                'current_rank': current_rank,
                'prev_rank': prev_rank
            })
        
        # Analyze current gameweek
        gw_data = manager['gameweek_data'].get(str(gameweek), {})
        picks = gw_data.get('picks', [])
        entry_history = gw_data.get('entry_history', {})
        
        # Find captain
        captain_pick = next((p for p in picks if p.get('is_captain', False)), None)
        if captain_pick:
            captain_id = captain_pick['element']
            captain_points = player_id_to_points.get(captain_id, 0) * captain_pick.get('multiplier', 1)
            captain_name = player_id_to_name.get(captain_id, 'Unknown')

            # Captain fail (2 points or less) - only once the captain has played
            if captain_points <= 2 and _finished(captain_id):
                captain_fails.append({
                    'manager': manager_name,
                    'captain': captain_name,
                    'points': captain_points
                })
        
        # Find bench heroes (high scorers on bench)
        bench_players = [p for p in picks if p['position'] > 11]
        for bench_pick in bench_players:
            player_id = bench_pick['element']
            points = player_id_to_points.get(player_id, 0)
            if points >= 8 and _finished(player_id):  # Significant points on bench
                bench_heroes.append({
                    'manager': manager_name,
                    'player': player_id_to_name.get(player_id, 'Unknown'),
                    'points': points
                })
        
        # Find differential heroes (low ownership, high points)
        starting_players = [p for p in picks if p['position'] <= 11]
        for pick in starting_players:
            player_id = pick['element']
            points = player_id_to_points.get(player_id, 0)
            ownership = sum(1 for m in mini_league_data['standings']['results'] 
                          if any(p['element'] == player_id for p in m['gameweek_data'].get(str(gameweek), {}).get('picks', [])))
            ownership_pct = (ownership / total_managers) * 100
            
            if ownership_pct <= 33 and points >= 10 and _finished(player_id):  # Low ownership, high points
                differential_heroes.append({
                    'manager': manager_name,
                    'player': player_id_to_name.get(player_id, 'Unknown'),
                    'points': points,
                    'ownership_pct': ownership_pct
                })
    
    # Biggest rank jump (comeback) - show if moved up at least 1 place
    if rank_movements:
        positive_movements = [rm for rm in rank_movements if rm['change'] > 0]
        if positive_movements:
            biggest_jump = max(positive_movements, key=lambda x: x['change'])
            fun_facts['comeback'] = biggest_jump
    
    # Biggest rank drop (choke) - show if moved down at least 1 place
    if rank_movements:
        negative_movements = [rm for rm in rank_movements if rm['change'] < 0]
        if negative_movements:
            biggest_drop = min(negative_movements, key=lambda x: x['change'])
            fun_facts['choke'] = biggest_drop
    
    # Worst captain fail
    if captain_fails:
        worst_captain = min(captain_fails, key=lambda x: x['points'])
        fun_facts['captain_fail'] = worst_captain
    
    # Biggest bench hero
    if bench_heroes:
        biggest_bench_hero = max(bench_heroes, key=lambda x: x['points'])
        fun_facts['bench_hero'] = biggest_bench_hero
    
    # Best differential
    if differential_heroes:
        best_differential = max(differential_heroes, key=lambda x: x['points'])
        fun_facts['differential_hero'] = best_differential
    
    return fun_facts

def ascii_icon(letter: str) -> str:
    """
    Return a simple ASCII icon in a box with the given letter.
    For example:
      +---+
      | A |
      +---+
    """
    return f"+---+\n| {letter} |\n+---+"


def create_stats_table(interesting_stats: Dict, rankings_data: Dict, current_scores, fun_facts: Dict = None, gameweek: int = None) -> None:
    """Create a colorful and visually appealing table with aligned panels,
    displaying data entries in Weekly Performance panels, keeping ASCII icons
    in the Hall of Fame podium, and with increased vertical spacing between the
    Consistency King and Chaos Champion sections."""
    logger = logging.getLogger(__name__)
    
    # Set base font for regular text
    plt.rcParams["font.family"] = "DejaVu Sans"
    
    COLOR_PALETTE = {
        'title': '#2A2F4F',
        'accent1': '#4E944F',
        'accent2': '#E14D2A',
        'accent3': '#3F497F',
        'background': '#F8F6F4'
    }
    
    # Create the main figure and gridspec layout.
    fig = plt.figure(figsize=(18, 20), facecolor=COLOR_PALETTE['background'])
    gs = fig.add_gridspec(3, 2, height_ratios=[0.8, 1.8, 1.8], hspace=0.4, wspace=0.3)
    
    # ========== Title Section ==========
    ax_title = fig.add_subplot(gs[0, :])
    ax_title.axis('off')
    ax_title.text(0.5, 0.7, "FPL LEAGUE INSIGHTS", fontsize=40, fontweight='black',
                  ha='center', color=COLOR_PALETTE['title'], alpha=0.9,
                  transform=ax_title.transAxes)
    ax_title.text(0.5, 0.3, "Season Statistics & Performance Analysis", fontsize=24,
                  ha='center', color=COLOR_PALETTE['accent3'], alpha=0.8,
                  fontstyle='italic', transform=ax_title.transAxes)
    ax_title.text(0.98, 0.02, 
                  f"Generated: {datetime.now(pytz.timezone('America/Los_Angeles')).strftime('%d %b %Y %H:%M')} PST",
                  fontsize=16, ha='right', color='#666666', transform=ax_title.transAxes)
    
    # ========== Weekly Performance Section ==========
    ax_weekly = fig.add_subplot(gs[1, 0])
    ax_weekly.axis('off')
    
    def create_rounded_panel(ax, title: str, content: str, color: str,
                             y_center: float, panel_height: float = 0.30):
        """
        Create a panel with a rounded rectangle.
        y_center: vertical center of the panel.
        panel_height: total height of the panel.
        Displays a title (e.g., "Weekly Leader") and content (e.g., "90 pts\nManager X").
        """
        y_lower = y_center - panel_height / 2
        panel = FancyBboxPatch((0.05, y_lower), 0.9, panel_height,
                                 boxstyle="round,pad=0.1", ec="none", fc=color, alpha=0.15)
        ax.add_patch(panel)
        full_text = f"{title}\n{content}"
        ax.text(0.5, y_center, full_text, fontsize=20, fontweight='bold',
                color=color, va='center', ha='center')
        return panel

    # Data for Weekly Performance
    current_week_score = max(interesting_stats['current_scores'], key=lambda x: x['points'])
    leader_content = f"{current_week_score['points']} pts\n{current_week_score['manager']}"
    highest = interesting_stats['highest_weekly_score']
    record_content = f"{highest['score']} pts (GW{highest['gameweek']})\n{highest['manager']}"
    lowest = interesting_stats['lowest_weekly_score']
    low_content = f"{lowest['score']} pts (GW{lowest['gameweek']})\n{lowest['manager']}"
    
    # Use fixed vertical centers for three panels.
    leader_y = 0.8
    record_y = 0.5
    low_y = 0.2
    
    create_rounded_panel(ax_weekly, "Weekly Leader", leader_content, COLOR_PALETTE['accent1'], leader_y)
    create_rounded_panel(ax_weekly, "Record High", record_content, COLOR_PALETTE['accent3'], record_y)
    create_rounded_panel(ax_weekly, "Weekly Low", low_content, COLOR_PALETTE['accent2'], low_y)
    
    # ========== Hall of Fame Section ==========
    ax_hof = fig.add_subplot(gs[1, 1])
    ax_hof.axis('off')
    hof_bg = FancyBboxPatch((0.1, 0.1), 0.8, 0.8,
                             boxstyle="round,pad=0.1", ec=COLOR_PALETTE['accent3'],
                             fc=(*mcolors.to_rgb(COLOR_PALETTE['accent3']), 0.1))
    ax_hof.add_patch(hof_bg)
    
    # Compute Winners and Bananas based on Top 3 and Bottom 3 counts.
    winners = sorted(interesting_stats['mvps'], key=lambda x: x['top3_count'], reverse=True)[:3]
    bananas = sorted(interesting_stats['banana_awards'], key=lambda x: x['bottom3_count'], reverse=True)[:3]
    
    # Left side: WINNERS
    ax_hof.text(0.45, 0.85, "WINNERS", fontsize=26,
                ha='center', color=COLOR_PALETTE['accent3'], fontweight='bold')
    for i, manager in enumerate(winners, 1):
        ax_hof.text(0.55, 0.85 - i*0.1, f"{i}. {manager['manager']} ({manager['top3_count']} Top 3s)",
                    fontsize=22, ha='center', color=COLOR_PALETTE['accent3'])
    
    # Right side: BANANAS
    ax_hof.text(0.45, 0.4, "BANANAS", fontsize=26,
                ha='center', color=COLOR_PALETTE['accent2'], fontweight='bold')
    for i, manager in enumerate(bananas, 1):
        ax_hof.text(0.55, 0.4 - i*0.1, f"{i}. {manager['manager']} ({manager['bottom3_count']} Bottom 3s)",
                    fontsize=22, ha='center', color=COLOR_PALETTE['accent2'])

    
    # ========== Consistency Section ==========
    ax_consistency = fig.add_subplot(gs[2, 0])
    ax_consistency.axis('off')
    ax_consistency.add_patch(plt.Polygon([[0, 0.6], [1, 0.6], [1, 1], [0, 1]],
                                          color=COLOR_PALETTE['accent1'], alpha=0.08))
    ax_consistency.add_patch(plt.Polygon([[0, 0], [1, 0], [1, 0.4], [0, 0.4]],
                                          color=COLOR_PALETTE['accent2'], alpha=0.08))
    
    most_cons = interesting_stats['consistency']['most_consistent']
    ax_consistency.text(0.5, 0.8, "Consistency King", fontsize=24,
                        ha='center', color=COLOR_PALETTE['accent1'])
    # Increased vertical gap below the header.
    ax_consistency.text(0.5, 0.6, f"{most_cons['manager']}\nσ = {most_cons['std_dev']:.1f}",
                        fontsize=22, ha='center', linespacing=1.5)
    
    least_cons = interesting_stats['consistency']['least_consistent']
    ax_consistency.text(0.5, 0.3, "Chaos Champion", fontsize=24,
                        ha='center', color=COLOR_PALETTE['accent2'])
    ax_consistency.text(0.5, 0.1, f"{least_cons['manager']}\nσ = {least_cons['std_dev']:.1f}",
                        fontsize=22, ha='center', linespacing=1.5)
    
    # ========== Management Section ==========
    ax_mgmt = fig.add_subplot(gs[2, 1])
    ax_mgmt.axis('off')
    ax_mgmt.add_patch(FancyBboxPatch((0.1, 0.1), 0.75, 0.75,
                                     boxstyle="round,pad=0.1", ec=COLOR_PALETTE['accent2'],
                                     fc=(*mcolors.to_rgb(COLOR_PALETTE['accent2']), 0.08)))
    
    # Management header
    ax_mgmt.text(0.5, 0.7, "Management Challenges", fontsize=26,
                 ha='center', color=COLOR_PALETTE['accent2'])
    # Transfer Troubles section (stacked vertically)
    ax_mgmt.text(0.5, 0.60, "Transfer Troubles:", fontsize=24,
                 ha='center', color=COLOR_PALETTE['accent2'])
    transfer_start_y = 0.52
    for i, transfer in enumerate(interesting_stats['transfer_kings'][:3], 1):
        ax_mgmt.text(0.5, transfer_start_y - (i - 1) * 0.06,
                     f"{i}. {transfer['manager']} (-{transfer['transfer_hits']} pts)",
                     fontsize=18, ha='center')
    
    # Bench Blunders section with extra vertical space.
    ax_mgmt.text(0.5, 0.32, "Bench Blunders:", fontsize=24,
                 ha='center', color=COLOR_PALETTE['accent2'])
    bench_start_y = 0.25
    for i, bench in enumerate(interesting_stats['bench_masters'][:3], 1):
        ax_mgmt.text(0.5, bench_start_y - (i - 1) * 0.06,
                     f"{i}. {bench['manager']} ({bench['bench_points']} pts)",
                     fontsize=18, ha='center')
    
    plt.tight_layout()
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, 'interesting_stats.png'),
                dpi=300, bbox_inches='tight', facecolor=COLOR_PALETTE['background'])
    plt.close()

def plot_transfer_effectiveness(mini_league_data: Dict, gameweek: int, player_id_to_points: Dict, player_id_to_name: Dict,num) -> None:
    """Plot the transfer effectiveness comparing current gameweek with the previous gameweek."""
    import matplotlib.pyplot as plt
    import numpy as np
    import os
    import seaborn as sns
    from typing import Dict, List
    
    # Set style
    try:
        plt.style.use('seaborn-v0_8-darkgrid')  # 'seaborn' was removed in matplotlib>=3.6
    except OSError:
        pass
    
    # Create a larger figure
    plt.figure(figsize=(16, 10))
    
    # Create axes with space at bottom for legend
    ax = plt.gca()
    
    # Collect transfer data for each manager
    transfer_data = []
    
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        team_id = manager['entry']
        transfers = manager['transfers']  # All transfers
        
        # Get transfers made between last GW and this GW
        gw_transfers = [t for t in transfers if t['event'] == gameweek]
        
        if gw_transfers:
            # Calculate points from new players in current GW
            points_from_new_players = sum(player_id_to_points.get(t['element_in'], 0) for t in gw_transfers)
            
            # Get points that would have been scored by old players in current GW
            points_from_old_players = sum(player_id_to_points.get(t['element_out'], 0) for t in gw_transfers)
            
            # Get transfer cost for this gameweek
            gw_data = manager['gameweek_data'].get(str(gameweek), {})
            transfer_cost = gw_data.get('entry_history', {}).get('event_transfers_cost', 0)
            
            # Calculate net effect
            net_transfer_effect = points_from_new_players - points_from_old_players - transfer_cost
            
            transfer_data.append({
                'manager': manager_name,
                'num_transfers': len(gw_transfers),
                'points_gained': points_from_new_players,
                'points_foregone': points_from_old_players,
                'transfer_cost': transfer_cost,
                'net_effect': net_transfer_effect,
                'transfers_detail': [
                    {
                        'out': player_id_to_name.get(t['element_out'], 'Unknown'),
                        'out_points': player_id_to_points.get(t['element_out'], 0),
                        'in': player_id_to_name.get(t['element_in'], 'Unknown'),
                        'in_points': player_id_to_points.get(t['element_in'], 0)
                    } for t in gw_transfers
                ]
            })
        else:
            # No transfers made
            transfer_data.append({
                'manager': manager_name,
                'num_transfers': 0,
                'points_gained': 0,
                'points_foregone': 0,
                'transfer_cost': 0,
                'net_effect': 0,
                'transfers_detail': []
            })
    
    # Sort by net effect
    transfer_data.sort(key=lambda x: x['net_effect'], reverse=True)
    
    # Prepare data for plotting
    managers = [d['manager'] for d in transfer_data]
    net_effects = [d['net_effect'] for d in transfer_data]
    
    # Create color map based on net effect
    colors = ['green' if x > 0 else 'red' for x in net_effects]
    
    # Create bar plot
    bars = ax.bar(managers, net_effects, color=colors)
    
    # Customize the plot
    ax.set_title(f'Transfer Effectiveness (GW{gameweek-1} → GW{gameweek})', 
             fontsize=16, fontweight='bold', pad=20)
    ax.set_xlabel('Managers', fontsize=14, fontweight='bold')
    ax.set_ylabel('Net Points from Transfers', fontsize=14, fontweight='bold')
    
    # Rotate x-axis labels
    plt.xticks(rotation=45, ha='right', fontsize=12)
    plt.yticks(fontsize=12)
    
    # Add zero line
    ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    
    # Add value labels on bars
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2,
                height if height >= 0 else height - 1,
                f'{int(height)}',
                ha='center', va='bottom' if height >= 0 else 'top',
                fontsize=12, fontweight='bold',
                color='black')  # Ensure text is visible regardless of bar color
    
    # Create detailed legend entries with better formatting
    legend_entries = []
    max_transfers = max(d['num_transfers'] for d in transfer_data)
    columns = min(3, max_transfers + 1)
    
    for d in transfer_data:
        if d['num_transfers'] > 0:
            # Simple bold for manager name using regular string
            entry = [f"{d['manager']} ({d['num_transfers']} transfer{'s' if d['num_transfers']>1 else ''})"]
            for t in d['transfers_detail']:
                diff = t['in_points'] - t['out_points']
                sign = '+' if diff > 0 else ''
                entry.append(f"    {t['out']}({t['out_points']}) → {t['in']}({t['in_points']}) [{sign}{diff}]")
            if d['transfer_cost'] > 0:
                entry.append(f"    Cost: -{d['transfer_cost']}")
            entry.append(f"    Net: {d['net_effect']}")
            legend_entries.append('\n'.join(entry))
        else:
            legend_entries.append(f"{d['manager']}\n    No transfers")
    
    # Add legend below the plot with adjusted spacing and larger fontsize
    ax.legend(bars, legend_entries,
             title="Transfer Details",
             loc='upper center',
             bbox_to_anchor=(0.5, -0.1),
             fontsize=12,  # Increased font size
             title_fontsize=14,
             ncol=columns,
             bbox_transform=plt.gcf().transFigure,
             frameon=True,
             shadow=True,
             handlelength=1,
             handletextpad=1)
    
    # Add grid
    ax.grid(True, axis='y', alpha=0.3)
    
    # Adjust layout to make room for legend
    plt.subplots_adjust(bottom=0.3)  # Increase bottom margin for legend
    
    # Save the plot with higher resolution
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'{num}_transfer_effectiveness_gw{gameweek}.png'), 
                dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def plot_team_value(mini_league_data: Dict, gameweek: int,num) -> None:
    """Plot the team value and bank money for each manager in the gameweek."""
    # Collect team value data
    team_values = []
    for manager in mini_league_data['standings']['results']:
        gw_data = manager['gameweek_data'].get(str(gameweek), {})
        entry_history = gw_data.get('entry_history', {})
        team_value = entry_history.get('value', 0) / 10  # Convert to actual value
        bank = entry_history.get('bank', 0) / 10  # Convert to actual value
        squad_value = team_value - bank  # Value in playing squad
        
        team_values.append({
            'manager': manager['entry_name'],
            'squad_value': squad_value,
            'bank': bank,
            'total_value': team_value
        })
    
    # Convert to DataFrame and sort by total value
    df = pd.DataFrame(team_values)
    df = df.sort_values('total_value', ascending=False)
    
    # Create plot
    plt.figure(figsize=(15, 10))
    ax = plt.gca()
    
    # Create stacked bars
    squad_bars = plt.bar(range(len(df)), df['squad_value'].values, 
                        label='Squad Value', color='royalblue')
    bank_bars = plt.bar(range(len(df)), df['bank'].values, 
                        bottom=df['squad_value'].values,
                        label='Money in Bank', color='lightgreen')
    
    # Customize plot
    plt.title(f'Team Value Breakdown - Gameweek {gameweek}', 
             fontsize=14, fontweight='bold', pad=20)
    plt.xlabel('Managers', fontsize=12, fontweight='bold')
    plt.ylabel('Value (£M)', fontsize=12, fontweight='bold')
    
    # Create x-tick labels with both manager name and total value
    x_labels = [f"{manager} (£{value:.1f}M)" for manager, value 
                in zip(df['manager'].values, df['total_value'].values)]
    
    # Set x-ticks with combined labels
    plt.xticks(range(len(df)), x_labels, rotation=45, ha='right', fontsize=10)
    plt.yticks(fontsize=10)
    
    # Add grid
    ax.grid(True, axis='y', alpha=0.3)
    
    # Add value labels on the bars
    def add_labels(bars, values):
        for i, (bar, value) in enumerate(zip(bars, values)):
            if value > 0:  # Only add label if value is positive
                ax.text(bar.get_x() + bar.get_width()/2,
                       bar.get_y() + bar.get_height()/2,
                       f'£{value:.1f}M',
                       ha='center', va='center',
                       fontsize=10,
                       color='white')
    
    # Add labels for squad value and bank amounts
    add_labels(squad_bars, df['squad_value'].values)
    add_labels(bank_bars, df['bank'].values)
    
    # Customize legend with adjusted position
    plt.legend(loc='center left',
              bbox_to_anchor=(1.02, 0.5),
              fontsize=10,
              frameon=True,
              shadow=True)
    
    # Adjust layout with extra space on right for legend
    plt.subplots_adjust(right=0.85)
    
    # Save plot
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'{num}_team_value_gw{gameweek}.png'), 
                dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def plot_weekly_rankings_distribution(mini_league_data: Dict, num: int) -> None:
    """Plot distribution of weekly rankings (1st, 2nd, 3rd place finishes) for each manager."""
    plt.figure(figsize=(15, 10))
    
    # Track rankings for each manager
    rankings_data = {
        'first': defaultdict(int),
        'second': defaultdict(int),
        'third': defaultdict(int)
    }
    
    # Calculate most points per gameweek
    all_gameweeks = set()
    gameweek_scores = defaultdict(list)
    
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        for gw_data in manager['history']['current']:
            all_gameweeks.add(gw_data['event'])
            net_pts = gw_data['points'] - gw_data.get('event_transfers_cost', 0)  # NET points
            gameweek_scores[gw_data['event']].append({
                'manager': manager_name,
                'points': net_pts
            })
    
    # Calculate rankings for each gameweek
    for gw in all_gameweeks:
        scores = gameweek_scores[gw]
        sorted_scores = sorted(scores, key=lambda x: x['points'], reverse=True)
        
        if len(sorted_scores) >= 1:
            rankings_data['first'][sorted_scores[0]['manager']] += 1
        if len(sorted_scores) >= 2:
            rankings_data['second'][sorted_scores[1]['manager']] += 1
        if len(sorted_scores) >= 3:
            rankings_data['third'][sorted_scores[2]['manager']] += 1
    
    # Prepare data for plotting
    managers = list(set(manager['entry_name'] for manager in mini_league_data['standings']['results']))
    first_counts = [rankings_data['first'][m] for m in managers]
    second_counts = [rankings_data['second'][m] for m in managers]
    third_counts = [rankings_data['third'][m] for m in managers]
    
    # Create stacked bar chart
    x = range(len(managers))
    width = 0.35
    
    plt.bar(x, first_counts, width, label='1st Place', color='gold')
    plt.bar(x, second_counts, width, bottom=first_counts, label='2nd Place', color='silver')
    plt.bar(x, third_counts, width, bottom=[i+j for i,j in zip(first_counts, second_counts)], 
            label='3rd Place', color='#CD7F32')
    
    plt.xlabel('Managers', fontsize=12, fontweight='bold')
    plt.ylabel('Number of Weekly Finishes', fontsize=12, fontweight='bold')
    plt.title('Distribution of Weekly Top 3 Finishes', fontsize=14, fontweight='bold')
    plt.xticks(x, managers, rotation=45, ha='right')
    
    # Add legend
    plt.legend()
    
    # Add value labels on the bars
    for i in range(len(managers)):
        if first_counts[i] > 0:
            plt.text(i, first_counts[i]/2, str(first_counts[i]), ha='center', va='center')
        if second_counts[i] > 0:
            plt.text(i, first_counts[i] + second_counts[i]/2, str(second_counts[i]), ha='center', va='center')
        if third_counts[i] > 0:
            plt.text(i, first_counts[i] + second_counts[i] + third_counts[i]/2, 
                    str(third_counts[i]), ha='center', va='center')
    
    plt.tight_layout()
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'{num}_weekly_rankings_distribution.png'), 
                dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    
    return rankings_data




def generate_all_plots(mini_league_data: Dict, gameweek: int, player_id_to_name: Dict, player_id_to_points: Dict, player_id_to_position: Dict) -> None:
    """Generate all plots for the gameweek."""
    try:
        plot_performance_timeline(mini_league_data, num=3)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error generating performance timeline plot: {e}")
    create_all_points_heatmap(mini_league_data, num=8)
    plot_captain_choices(mini_league_data, gameweek, player_id_to_name, player_id_to_points, num=6)
    plot_number_of_weekly_winners(mini_league_data, num=4)
    plot_transfer_effectiveness(mini_league_data, gameweek, player_id_to_points, player_id_to_name, num=5)
    plot_team_value(mini_league_data, gameweek, num=7)
    plot_player_distribution(mini_league_data, gameweek, player_id_to_name, player_id_to_points, num=2)
    plot_position_wise_points(mini_league_data, gameweek, player_id_to_name, player_id_to_points, player_id_to_position, num=10)
    rankings_data = plot_weekly_rankings_distribution(mini_league_data, num=9)
    interesting_stats = calculate_interesting_stats(mini_league_data, player_id_to_name, player_id_to_points)
    # Use entry_history points (final score) which is NET points after transfer costs
    current_scores = []
    for manager in mini_league_data['standings']['results']:
        gw_data = manager.get('gameweek_data', {}).get(str(gameweek), {})
        entry_history = gw_data.get('entry_history', {})
        gross_points = entry_history.get('points', 0)  # API returns GROSS points
        transfer_cost = entry_history.get('event_transfers_cost', 0)  # Hit taken
        net_points = gross_points - transfer_cost  # NET points after hit deduction
        current_scores.append({
            'manager': manager['entry_name'],
            'points': net_points,  # Keep 'points' as NET for backward compatibility
            'net_points': net_points,
            'gross_points': gross_points,
            'transfer_cost': transfer_cost,
            'took_hit': transfer_cost > 0
        })
    interesting_stats['current_scores'] = current_scores
    
    # Calculate weekly fun facts
    fun_facts = calculate_weekly_fun_facts(mini_league_data, gameweek, player_id_to_name, player_id_to_points)

    create_stats_table(interesting_stats, rankings_data, current_scores, fun_facts, gameweek)
    
    # Note: plot_gw_vs_overall_analysis (plot 1) is created in main() after AI insights are generated
    # PDF generation will wait for all plots to be ready

def analyze_player_distribution(mini_league_data: Dict, gameweek: int, player_id_to_name: Dict, player_id_to_points: Dict) -> Dict:
    """Analyze player distribution across teams and their performance."""
    # Initialize tracking dictionaries
    player_ownership = defaultdict(int)  # How many teams own each player
    player_points = defaultdict(int)     # Points for each player
    player_teams = defaultdict(set)      # Which teams own each player
    player_starts = defaultdict(int)     # How many teams started each player
    captain_picks = defaultdict(int)     # How many teams captained each player
    
    total_managers = len(mini_league_data['standings']['results'])
    
    # Analyze each team's players
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        gw_data = manager['gameweek_data'].get(str(gameweek), {})
        picks = gw_data.get('picks', [])
        
        for pick in picks:
            player_id = pick['element']
            
            # Track overall ownership
            player_ownership[player_id] += 1
            player_points[player_id] = player_id_to_points.get(player_id, 0)
            player_teams[player_id].add(manager_name)
            
            # Track starting players (position <= 11)
            if pick['position'] <= 11:
                player_starts[player_id] += 1
            
            # Track captain picks
            if pick.get('is_captain', False):
                captain_picks[player_id] += 1
    
    # Calculate various player statistics
    stats = {
        'most_owned': [],
        'highest_scoring': [],
        'top_differentials': [],
        'most_captained': [],
        'bench_heroes': []
    }
    
    # Most owned players
    most_owned = sorted(
        [(pid, count) for pid, count in player_ownership.items()],
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    stats['most_owned'] = [
        {
            'name': player_id_to_name[pid],
            'count': count,
            'ownership_pct': round(count/total_managers * 100, 1),
            'points': player_points[pid]
        }
        for pid, count in most_owned
    ]
    
    # Highest scoring players
    highest_scoring = sorted(
        [(pid, pts) for pid, pts in player_points.items()],
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    stats['highest_scoring'] = [
        {
            'name': player_id_to_name[pid],
            'points': pts,
            'ownership': len(player_teams[pid]),
            'ownership_pct': round(len(player_teams[pid])/total_managers * 100, 1)
        }
        for pid, pts in highest_scoring
    ]
    
    # Top differentials (good points, low ownership)
    differentials = sorted(
        [(pid, pts) for pid, pts in player_points.items()
         if len(player_teams[pid]) <= total_managers / 3  # Owned by less than 1/3 of teams
         and pts > 0],  # Must have scored points
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    stats['top_differentials'] = [
        {
            'name': player_id_to_name[pid],
            'points': pts,
            'ownership': len(player_teams[pid]),
            'ownership_pct': round(len(player_teams[pid])/total_managers * 100, 1)
        }
        for pid, pts in differentials
    ]
    
    # Most captained players
    most_captained = sorted(
        [(pid, count) for pid, count in captain_picks.items()],
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    stats['most_captained'] = [
        {
            'name': player_id_to_name[pid],
            'captain_count': count,
            'captain_pct': round(count/total_managers * 100, 1),
            'points': player_points[pid]
        }
        for pid, count in most_captained
    ]
    
    # Bench heroes (high scoring but frequently benched)
    bench_heroes = sorted(
        [(pid, pts) for pid, pts in player_points.items()
         if player_ownership[pid] > 0  # Must be owned
         and player_starts[pid] < player_ownership[pid]/2],  # Benched in more than half of teams
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    stats['bench_heroes'] = [
        {
            'name': player_id_to_name[pid],
            'points': pts,
            'total_owners': player_ownership[pid],
            'benched_count': player_ownership[pid] - player_starts[pid]
        }
        for pid, pts in bench_heroes
    ]
    
    return stats

def plot_player_distribution(mini_league_data: Dict, gameweek: int, player_id_to_name: Dict, player_id_to_points: Dict, num: int) -> None:
    """Create visualizations for player distribution analysis focusing on differentials and performance trends."""
    
    # Initialize tracking dictionaries
    player_ownership = defaultdict(int)      # How many teams own each player
    player_points = defaultdict(int)         # Points for each player
    player_teams = defaultdict(set)          # Which teams own each player
    
    total_managers = len(mini_league_data['standings']['results'])
    
    # Get all manager names first to ensure consistency
    manager_names = [manager['entry_name'] for manager in mini_league_data['standings']['results']]
    
    # Collect historical data first
    historical_points = {name: [] for name in manager_names}  # Initialize for all managers
    
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        # Get historical weekly points
        for gw_hist in manager['history']['current']:
            week_points = gw_hist['points']
            historical_points[manager_name].append(week_points)
    
    # Calculate historical medians and normalize them
    historical_medians = {}
    all_medians = []
    for manager_name in manager_names:
        points = historical_points[manager_name]
        if len(points) > 1:  # Make sure we have enough points
            median = np.median(points[:-1])  # Exclude current week
            historical_medians[manager_name] = median
            all_medians.append(median)
    
    # Normalize historical medians
    min_median = min(all_medians) if all_medians else 0
    max_median = max(all_medians) if all_medians else 1
    median_range = max_median - min_median if max_median > min_median else 1
    
    normalized_historical_medians = {
        manager: (median - min_median) / median_range
        for manager, median in historical_medians.items()
    }
    
    # Collect current gameweek data
    current_points = {}
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        gw_data = manager['gameweek_data'].get(str(gameweek), {})
        picks = gw_data.get('picks', [])
        
        # Track current week points
        total_points = 0
        num_players = 0
        
        for pick in picks:
            player_id = pick['element']
            points = player_id_to_points.get(player_id, 0)
            
            if points > 0:  # Only consider players who played
                player_ownership[player_id] += 1
                player_points[player_id] = points
                player_teams[player_id].add(manager_name)
                total_points += points
                num_players += 1
        
        if num_players > 0:
            current_points[manager_name] = total_points / num_players
    
    # Normalize current week points
    min_current = min(current_points.values()) if current_points else 0
    max_current = max(current_points.values()) if current_points else 1
    current_range = max_current - min_current if max_current > min_current else 1
    
    normalized_current = {
        manager: (points - min_current) / current_range
        for manager, points in current_points.items()
    }
    
    # Create figure with better styling
    fig = plt.figure(figsize=(20, 16), facecolor='white')
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 1.5], hspace=0.35)
    
    # 1. Differential Players (Top) - Improved styling
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor('#f8f9fa')
    
    # Simplify differential analysis
    differential_players = []
    for pid, points in player_points.items():
        ownership_pct = (player_ownership[pid] / total_managers) * 100
        if ownership_pct < 33 and points > 0:  # Low ownership but scored points
            differential_players.append({
                'name': player_id_to_name.get(pid, 'Unknown'),
                'points': points,
                'ownership': ownership_pct,
                'teams': ', '.join(sorted(list(player_teams[pid]))[:3])  # Limit teams shown
            })
    
    # Sort and get top differentials
    differential_players.sort(key=lambda x: x['points'], reverse=True)
    top_differentials = differential_players[:5]
    
    if top_differentials:  # Only plot if we have differentials
        names = [d['name'] for d in top_differentials]
        points = [d['points'] for d in top_differentials]
        ownership = [d['ownership'] for d in top_differentials]
        
        # Create gradient colors based on points
        colors = plt.cm.viridis(np.linspace(0.3, 0.9, len(names)))
        bars = ax1.bar(range(len(names)), points, color=colors, alpha=0.8, edgecolor='black', linewidth=1.5)
        
        # Add value labels on bars
        for i, (bar, pts) in enumerate(zip(bars, points)):
            ax1.text(bar.get_x() + bar.get_width()/2., pts,
                    f'{int(pts)} pts',
                    ha='center', va='bottom', fontsize=11, fontweight='bold')
        
        # Add ownership info below
        for i, d in enumerate(top_differentials):
            ax1.text(i, -max(points)*0.05, f"{d['ownership']:.1f}% owned",
                    ha='center', va='top', fontsize=9, style='italic', color='gray')
        
        ax1.set_title('Top Differential Players (High Impact, Low Ownership)', 
                     fontsize=16, fontweight='bold', pad=20, color='#2c3e50')
        ax1.set_xticks(range(len(names)))
        ax1.set_xticklabels(names, rotation=15, ha='right', fontsize=11)
        ax1.set_ylabel('Points', fontsize=12, fontweight='bold')
        ax1.grid(axis='y', alpha=0.3, linestyle='--')
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
    else:
        ax1.text(0.5, 0.5, 'No differential players found', 
                 ha='center', va='center', fontsize=14, style='italic')
    
    # 2. Historical vs Current Performance (Bottom) - Improved styling
    ax2 = fig.add_subplot(gs[1])
    ax2.set_facecolor('#f8f9fa')
    
    # Only include managers that have both historical and current data
    valid_managers = [m for m in manager_names 
                     if m in normalized_historical_medians and m in normalized_current]
    
    if valid_managers:
        # Sort managers by historical median
        sorted_managers = sorted(
            [(m, normalized_historical_medians[m]) for m in valid_managers],
            key=lambda x: x[1],
            reverse=True
        )
        manager_names_sorted = [m[0] for m in sorted_managers]
        
        # Plot data
        x = range(len(manager_names_sorted))
        historical = [normalized_historical_medians[m] for m in manager_names_sorted]
        current = [normalized_current[m] for m in manager_names_sorted]
        
        # Plot historical median as bars with gradient
        bar_colors = plt.cm.Greys(np.linspace(0.3, 0.7, len(x)))
        bars = ax2.bar(x, historical, alpha=0.4, color=bar_colors, 
                      edgecolor='gray', linewidth=1, label='Historical Median', zorder=1)
        
        # Plot current week as larger, colored points
        point_colors = ['#2ecc71' if curr > hist else '#e74c3c' 
                       for hist, curr in zip(historical, current)]
        ax2.scatter(x, current, color=point_colors, s=150, zorder=5, 
                   edgecolors='black', linewidths=1.5, label='Current Week')
        
        # Connect historical to current with lines, color coded
        for i, (hist, curr) in enumerate(zip(historical, current)):
            color = '#2ecc71' if curr > hist else '#e74c3c'
            ax2.plot([i, i], [hist, curr], color=color, linestyle='-', 
                    linewidth=2, alpha=0.6, zorder=2)
        
        # Customize plot
        ax2.set_title('Manager Performance: Historical vs Current Week (Normalized Scores)', 
                     fontsize=16, fontweight='bold', pad=20, color='#2c3e50')
        ax2.set_xticks(x)
        ax2.set_xticklabels(manager_names_sorted, rotation=45, ha='right', fontsize=10)
        ax2.set_ylabel('Normalized Score (0-1)', fontsize=12, fontweight='bold')
        ax2.set_xlabel('Managers', fontsize=12, fontweight='bold')
        
        # Add legend
        ax2.legend(loc='upper right', fontsize=11, framealpha=0.9)
        ax2.axhline(y=0.5, color='gray', linestyle='--', alpha=0.5, linewidth=1)
        ax2.text(len(manager_names_sorted)-1, 0.52, 'League Average', 
                 ha='right', va='bottom', color='gray', alpha=0.7, fontsize=9)
        
        # Add annotations for each manager
        for i, (hist, curr) in enumerate(zip(historical, current)):
            change = (curr - hist) * 100
            color = '#2ecc71' if change > 0 else '#e74c3c'
            ax2.text(i, max(hist, curr) + 0.03, 
                     f'{change:+.1f}%', 
                     ha='center', va='bottom',
                     color=color, fontweight='bold', fontsize=9)
        
        ax2.grid(axis='y', alpha=0.3, linestyle='--')
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
    else:
        ax2.text(0.5, 0.5, 'Insufficient data for performance comparison', 
                 ha='center', va='center', fontsize=14, style='italic')
    
    plt.suptitle(f'Player Distribution Analysis - Gameweek {gameweek}', 
                fontsize=18, fontweight='bold', y=0.98, color='#2c3e50')
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    
    # Save the plot
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'{num}_player_distribution.png'),
                dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def plot_position_wise_points(mini_league_data: Dict, gameweek: int, player_id_to_name: Dict, 
                              player_id_to_points: Dict, player_id_to_position: Dict, num: int) -> None:
    """Create a heatmap showing points scored by each position (GK, DEF, MID, FWD) for all managers."""
    # Position mapping: 1=GK, 2=DEF, 3=MID, 4=FWD
    position_names = {1: 'Goalkeeper', 2: 'Defender', 3: 'Midfielder', 4: 'Forward'}
    position_short = {1: 'GK', 2: 'DEF', 3: 'MID', 4: 'FWD'}
    
    # Collect position-wise points for each manager
    manager_data = []
    manager_names = []
    
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        manager_names.append(manager_name)
        
        gw_data = manager['gameweek_data'].get(str(gameweek), {})
        picks = gw_data.get('picks', [])
        
        # Calculate points by position (only starting XI)
        position_points = {1: 0, 2: 0, 3: 0, 4: 0}
        
        for pick in picks:
            if pick['position'] <= 11:  # Only starting XI
                player_id = pick['element']
                player_position = player_id_to_position.get(player_id, 0)
                player_points = player_id_to_points.get(player_id, 0)
                multiplier = pick.get('multiplier', 1)
                
                if player_position in position_points:
                    position_points[player_position] += player_points * multiplier
        
        manager_data.append([
            position_points[1],  # GK
            position_points[2],  # DEF
            position_points[3],  # MID
            position_points[4]   # FWD
        ])
    
    # Create DataFrame for heatmap
    df = pd.DataFrame(manager_data, 
                     index=manager_names,
                     columns=[position_short[1], position_short[2], position_short[3], position_short[4]])
    
    # Sort by total points (descending)
    df['Total'] = df.sum(axis=1)
    df = df.sort_values('Total', ascending=False)
    df = df.drop('Total', axis=1)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, max(8, len(manager_names) * 0.5)), facecolor='white')
    
    # Create heatmap with better colormap
    sns.heatmap(df, annot=True, fmt='d', cmap='YlOrRd', 
                cbar_kws={'label': 'Points', 'shrink': 0.8},
                linewidths=1, linecolor='white',
                ax=ax, vmin=0)
    
    # Customize plot
    ax.set_title(f'Position-wise Points Distribution - Gameweek {gameweek}\n'
                f'(Points scored by each position in starting XI)',
                fontsize=16, fontweight='bold', pad=20, color='#2c3e50')
    ax.set_xlabel('Position', fontsize=13, fontweight='bold')
    ax.set_ylabel('Managers', fontsize=13, fontweight='bold')
    
    # Rotate y-axis labels for better readability
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, ha='right', fontsize=10)
    ax.set_xticklabels(ax.get_xticklabels(), fontsize=11, fontweight='bold')
    
    # Add total points column on the right
    totals = df.sum(axis=1).values
    for i, total in enumerate(totals):
        ax.text(len(df.columns) + 0.5, i + 0.5, f'{int(total)}',
               ha='center', va='center', fontsize=10, fontweight='bold',
               bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.7))
    
    # Add "Total" label
    ax.text(len(df.columns) + 0.5, -0.5, 'Total',
           ha='center', va='top', fontsize=11, fontweight='bold')
    
    plt.tight_layout()
    
    # Save the plot
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'{num}_position_wise_points_gw{gameweek}.png'),
                dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def add_player_stats_to_table(text: List[str], stats: Dict) -> List[str]:
    """Add player distribution statistics to the stats table."""
    text.append("\nPLAYER DISTRIBUTION ANALYSIS")
    text.append("-------------------------")
    
    # Most owned players
    text.append("\nMost Owned Players:")
    for player in stats['most_owned']:
        text.append(f"  • {player['name']}: {player['ownership_pct']}% ownership ({player['points']} points)")
    
    # Highest scoring
    text.append("\nHighest Scoring Players:")
    for player in stats['highest_scoring']:
        text.append(f"  • {player['name']}: {player['points']} points ({player['ownership_pct']}% ownership)")
    
    # Differentials
    text.append("\nTop Differentials:")
    for player in stats['top_differentials']:
        text.append(f"  • {player['name']}: {player['points']} points (only {player['ownership_pct']}% ownership)")
    
    # Most captained
    text.append("\nMost Captained Players:")
    for player in stats['most_captained']:
        text.append(f"  • {player['name']}: Captained by {player['captain_pct']}% ({player['points']} points)")
    
    # Bench heroes
    text.append("\nBench Heroes:")
    for player in stats['bench_heroes']:
        text.append(f"  • {player['name']}: {player['points']} points (benched in {player['benched_count']}/{player['total_owners']} teams)")
    
    return text



def gather_rich_insights_data(mini_league_data: Dict, gameweek: int, current_scores: List,
                               player_id_to_name: Dict = None, player_id_to_points: Dict = None,
                               play_status: Dict = None) -> Dict:
    """Gather comprehensive data for AI insights including historical trends, player performance, and rivalries."""
    insights_data = {}
    managers = mini_league_data['standings']['results']
    total_managers = len(managers)
    
    # 1. Current GW standings (using NET points - after hit deductions)
    gw_standings = sorted(current_scores, key=lambda x: x.get('points', x.get('net_points', 0)), reverse=True)
    insights_data['gw_winner'] = gw_standings[0] if gw_standings else None
    insights_data['gw_loser'] = gw_standings[-1] if gw_standings else None
    insights_data['gw_avg'] = sum(s.get('points', s.get('net_points', 0)) for s in current_scores) / len(current_scores) if current_scores else 0
    
    # Calculate gross average too
    gross_points = [s.get('gross_points', s.get('points', 0)) for s in current_scores]
    insights_data['gw_gross_avg'] = sum(gross_points) / len(gross_points) if gross_points else 0
    
    # Total hits taken this GW
    total_hits = sum(s.get('transfer_cost', 0) for s in current_scores)
    insights_data['total_hits_this_gw'] = total_hits
    
    # 2. Overall standings
    overall_standings = sorted(managers, key=lambda x: x.get('total', 0), reverse=True)
    insights_data['leader'] = overall_standings[0]['entry_name'] if overall_standings else None
    insights_data['leader_total'] = overall_standings[0].get('total', 0) if overall_standings else 0
    insights_data['last_place'] = overall_standings[-1]['entry_name'] if overall_standings else None
    
    # Calculate gap to leader for each manager
    leader_points = insights_data['leader_total']
    gaps_to_leader = []
    for idx, m in enumerate(overall_standings[1:], 2):
        gaps_to_leader.append({
            'manager': m['entry_name'],
            'gap': leader_points - m.get('total', 0),
            'rank': idx
        })
    insights_data['gaps_to_leader'] = gaps_to_leader
    
    # 3. Form analysis (last 5 GWs)
    form_data = []
    streak_data = []
    for manager in managers:
        manager_name = manager['entry_name']
        history = manager['history']['current']
        
        if len(history) >= 2:
            # Last 5 GWs form - use NET points (subtract transfer costs)
            last_5 = history[-5:] if len(history) >= 5 else history
            last_5_avg = np.mean([h['points'] - h.get('event_transfers_cost', 0) for h in last_5])
            season_avg = np.mean([h['points'] - h.get('event_transfers_cost', 0) for h in history])
            current_gw_pts = next((s['points'] for s in current_scores if s['manager'] == manager_name), 0)
            
            # Form trend (above/below personal average)
            form_diff = last_5_avg - season_avg
            form_data.append({
                'manager': manager_name,
                'last_5_avg': round(last_5_avg, 1),
                'season_avg': round(season_avg, 1),
                'form_diff': round(form_diff, 1),
                'current_vs_avg': round(current_gw_pts - season_avg, 1),
                'is_hot': form_diff > 3,
                'is_cold': form_diff < -3
            })
            
            # Calculate streaks (consecutive above/below average)
            streak = 0
            streak_type = None
            for h in reversed(history):
                h_net_pts = h['points'] - h.get('event_transfers_cost', 0)  # NET points
                if h_net_pts >= season_avg + 5:
                    if streak_type == 'hot' or streak_type is None:
                        streak += 1
                        streak_type = 'hot'
                    else:
                        break
                elif h_net_pts <= season_avg - 5:
                    if streak_type == 'cold' or streak_type is None:
                        streak += 1
                        streak_type = 'cold'
                    else:
                        break
                else:
                    break
            
            if streak >= 2:
                streak_data.append({
                    'manager': manager_name,
                    'streak': streak,
                    'type': streak_type
                })
    
    insights_data['form'] = sorted(form_data, key=lambda x: x['form_diff'], reverse=True)
    insights_data['streaks'] = streak_data
    
    # Find hottest and coldest form
    if form_data:
        insights_data['hottest_form'] = max(form_data, key=lambda x: x['form_diff'])
        insights_data['coldest_form'] = min(form_data, key=lambda x: x['form_diff'])
    
    # 4. Rank movements this GW
    rank_changes = []
    for manager in managers:
        manager_name = manager['entry_name']
        current_rank = manager.get('rank', 0)
        current_total = manager.get('total', 0)
        
        # Calculate previous rank
        current_gw_pts = next((s['points'] for s in current_scores if s['manager'] == manager_name), 0)
        prev_total = current_total - current_gw_pts
        
        # Get all previous totals
        all_prev_totals = []
        for m in managers:
            m_name = m['entry_name']
            m_current_pts = next((s['points'] for s in current_scores if s['manager'] == m_name), 0)
            all_prev_totals.append({
                'manager': m_name,
                'prev_total': m.get('total', 0) - m_current_pts
            })
        
        sorted_prev = sorted(all_prev_totals, key=lambda x: x['prev_total'], reverse=True)
        prev_rank = next((idx + 1 for idx, m in enumerate(sorted_prev) if m['manager'] == manager_name), current_rank)
        
        rank_change = prev_rank - current_rank
        if rank_change != 0:
            rank_changes.append({
                'manager': manager_name,
                'change': rank_change,
                'prev_rank': prev_rank,
                'current_rank': current_rank,
                'gw_points': current_gw_pts
            })
    
    insights_data['rank_changes'] = sorted(rank_changes, key=lambda x: x['change'], reverse=True)
    insights_data['biggest_climber'] = insights_data['rank_changes'][0] if insights_data['rank_changes'] else None
    insights_data['biggest_faller'] = insights_data['rank_changes'][-1] if insights_data['rank_changes'] else None
    
    # 5. Previous GW comparison
    prev_gw = gameweek - 1
    prev_gw_scores = []
    for manager in managers:
        manager_name = manager['entry_name']
        for gw_data in manager['history']['current']:
            if gw_data['event'] == prev_gw:
                net_pts = gw_data['points'] - gw_data.get('event_transfers_cost', 0)
                prev_gw_scores.append({
                    'manager': manager_name,
                    'points': net_pts  # NET points after hits
                })
                break
    
    if prev_gw_scores:
        prev_sorted = sorted(prev_gw_scores, key=lambda x: x['points'], reverse=True)
        insights_data['prev_gw_winner'] = prev_sorted[0]
        insights_data['prev_gw_avg'] = sum(s['points'] for s in prev_gw_scores) / len(prev_gw_scores)
        
        # Week-over-week changes for each manager
        wow_changes = []
        for curr in current_scores:
            prev = next((p for p in prev_gw_scores if p['manager'] == curr['manager']), None)
            if prev:
                wow_changes.append({
                    'manager': curr['manager'],
                    'current': curr['points'],
                    'previous': prev['points'],
                    'change': curr['points'] - prev['points']
                })
        insights_data['wow_changes'] = sorted(wow_changes, key=lambda x: x['change'], reverse=True)
        insights_data['biggest_improvement'] = insights_data['wow_changes'][0] if insights_data['wow_changes'] else None
        insights_data['biggest_decline'] = insights_data['wow_changes'][-1] if insights_data['wow_changes'] else None
    
    # 6. Captain analysis (if player data available)
    if player_id_to_name and player_id_to_points:
        captain_results = []
        for manager in managers:
            manager_name = manager['entry_name']
            gw_data = manager.get('gameweek_data', {}).get(str(gameweek), {})
            picks = gw_data.get('picks', [])
            
            captain_pick = next((p for p in picks if p.get('is_captain', False)), None)
            if captain_pick:
                captain_id = captain_pick['element']
                captain_base_pts = player_id_to_points.get(captain_id, 0)
                captain_total_pts = captain_base_pts * captain_pick.get('multiplier', 2)
                captain_name = player_id_to_name.get(captain_id, 'Unknown')
                
                cap_play = (play_status or {}).get(captain_id, 'upcoming')
                captain_results.append({
                    'manager': manager_name,
                    'captain': captain_name,
                    'points': captain_total_pts,
                    'base_points': captain_base_pts,
                    'play_status': cap_play,
                    # Only a fail/haul if the match is actually finished
                    'is_fail': captain_base_pts <= 2 and cap_play == 'finished',
                    'is_haul': captain_base_pts >= 10 and cap_play == 'finished',
                })

        if captain_results:
            insights_data['captain_results'] = sorted(captain_results, key=lambda x: x['points'], reverse=True)
            # best/worst only from finished captains to avoid misleading interim scores
            finished_caps = [c for c in captain_results if c['play_status'] == 'finished']
            insights_data['best_captain'] = (
                max(finished_caps, key=lambda x: x['points']) if finished_caps
                else insights_data['captain_results'][0]
            )
            insights_data['worst_captain'] = (
                min(finished_caps, key=lambda x: x['points']) if finished_caps
                else insights_data['captain_results'][-1]
            )

            # Captain fails only for captains who have actually played
            captain_fails = [c for c in captain_results if c['is_fail']]
            insights_data['captain_fails'] = captain_fails

            # Captain hauls (10+ base points, finished only)
            captain_hauls = [c for c in captain_results if c['is_haul']]
            insights_data['captain_hauls'] = captain_hauls
    
    # 7. Transfer analysis with NET points tracking (including hits)
    transfer_heroes = []
    transfer_villains = []
    hit_takers = []  # Track managers who took hits (transfer cost > 0)
    
    for manager in managers:
        manager_name = manager['entry_name']
        transfers = manager.get('transfers', [])
        gw_transfers = [t for t in transfers if t['event'] == gameweek]
        
        gw_data = manager.get('gameweek_data', {}).get(str(gameweek), {})
        entry_history = gw_data.get('entry_history', {})
        transfer_cost = entry_history.get('event_transfers_cost', 0)
        gross_points = entry_history.get('points', 0)  # API returns GROSS points
        net_points = gross_points - transfer_cost  # Calculate NET after hit
        
        # Track hit takers
        if transfer_cost > 0:
            hit_takers.append({
                'manager': manager_name,
                'hit_cost': transfer_cost,
                'gross_points': gross_points,
                'net_points': net_points,
                'num_transfers': entry_history.get('event_transfers', 0),
                'hit_worth_it': gross_points >= insights_data.get('gw_avg', 50) + transfer_cost  # Hit paid off if still above avg
            })
        
        if gw_transfers and player_id_to_points:
            points_gained = sum(player_id_to_points.get(t['element_in'], 0) for t in gw_transfers)
            points_lost = sum(player_id_to_points.get(t['element_out'], 0) for t in gw_transfers)
            
            net_transfer_effect = points_gained - points_lost - transfer_cost
            
            transfer_data = {
                'manager': manager_name,
                'num_transfers': len(gw_transfers),
                'net_effect': net_transfer_effect,
                'transfer_cost': transfer_cost,
                'gross_points': gross_points,
                'net_points': net_points,
                'transfers': [
                    f"{player_id_to_name.get(t['element_out'], '?')} → {player_id_to_name.get(t['element_in'], '?')}"
                    for t in gw_transfers[:2]  # Limit to 2 for brevity
                ]
            }
            
            if net_transfer_effect > 5:
                transfer_heroes.append(transfer_data)
            elif net_transfer_effect < -5:
                transfer_villains.append(transfer_data)
    
    insights_data['transfer_heroes'] = sorted(transfer_heroes, key=lambda x: x['net_effect'], reverse=True)
    insights_data['transfer_villains'] = sorted(transfer_villains, key=lambda x: x['net_effect'])
    
    # Sort hit takers by cost (biggest hits first)
    insights_data['hit_takers'] = sorted(hit_takers, key=lambda x: x['hit_cost'], reverse=True)
    insights_data['painful_hits'] = [h for h in hit_takers if not h['hit_worth_it']]
    insights_data['smart_hits'] = [h for h in hit_takers if h['hit_worth_it']]
    
    # 8. Bench points analysis
    bench_data = []
    for manager in managers:
        manager_name = manager['entry_name']
        for gw_hist in manager['history']['current']:
            if gw_hist['event'] == gameweek:
                bench_pts = gw_hist.get('points_on_bench', 0)
                bench_data.append({
                    'manager': manager_name,
                    'bench_points': bench_pts
                })
                break
    
    if bench_data:
        insights_data['bench_data'] = sorted(bench_data, key=lambda x: x['bench_points'], reverse=True)
        insights_data['most_bench_points'] = insights_data['bench_data'][0] if insights_data['bench_data'] else None
    
    # 9. Season records check
    records = []
    for manager in managers:
        manager_name = manager['entry_name']
        history = manager['history']['current']
        current_pts = next((s['points'] for s in current_scores if s['manager'] == manager_name), 0)
        
        if history:
            all_pts = [h['points'] - h.get('event_transfers_cost', 0) for h in history]  # NET points
            season_high = max(all_pts)
            season_low = min(all_pts)
            
            if current_pts >= season_high:
                records.append({'manager': manager_name, 'type': 'season_high', 'points': current_pts})
            elif current_pts <= season_low and gameweek > 1:
                records.append({'manager': manager_name, 'type': 'season_low', 'points': current_pts})
    
    insights_data['records'] = records
    
    # 10. Title race / relegation battle context
    if len(overall_standings) >= 3:
        top_3_gap = overall_standings[0].get('total', 0) - overall_standings[2].get('total', 0)
        insights_data['title_race_tight'] = top_3_gap <= 20
        
        bottom_3 = overall_standings[-3:]
        bottom_gap = bottom_3[0].get('total', 0) - bottom_3[-1].get('total', 0)
        insights_data['relegation_battle_tight'] = bottom_gap <= 15
    
    return insights_data


def build_yet_to_play_context(mini_league_data: Dict, gameweek: int, play_status: Dict,
                              player_id_to_name: Dict, player_id_to_points: Dict) -> str:
    """Per-manager summary of starting XI players still to play / mid-match,
    plus the captain's live state. Lets the pundit be accurate mid-gameweek."""
    if not play_status:
        return ""
    lines = []
    for m in mini_league_data['standings']['results']:
        picks = m.get('gameweek_data', {}).get(str(gameweek), {}).get('picks', [])
        starters = [p for p in picks if p['position'] <= 11]
        yet = [p for p in starters if play_status.get(p['element']) == 'upcoming']
        live = [p for p in starters if play_status.get(p['element']) == 'playing']
        cap = next((p for p in picks if p.get('is_captain')), None)
        cap_state = play_status.get(cap['element']) if cap else None
        cap_name = player_id_to_name.get(cap['element'], 'Unknown') if cap else 'N/A'
        if yet or live or cap_state in ('upcoming', 'playing'):
            note = []
            if yet:
                names = ", ".join(player_id_to_name.get(p['element'], '?') for p in yet[:3])
                note.append(f"{len(yet)} still to play ({names})")
            if live:
                note.append(f"{len(live)} mid-match")
            if cap_state in ('upcoming', 'playing'):
                note.append(f"captain {cap_name} {'yet to play' if cap_state == 'upcoming' else 'still playing'}")
            lines.append(f"- {m['entry_name']}: " + "; ".join(note))
    if not lines:
        return ""
    return "\n=== STILL TO PLAY (points are provisional) ===\n" + "\n".join(lines[:8])


def build_squad_play_status_context(mini_league_data: Dict, gameweek: int, play_status: Dict,
                                    player_id_to_name: Dict, player_id_to_points: Dict) -> str:
    """Per-manager starting-XI play status — makes it explicit who has played (even 0pts)."""
    if not play_status:
        return ""
    CHIP_LABELS = {'3xc': 'TRIPLE CAP', 'bboost': 'BENCH BOOST', 'freehit': 'FREE HIT', 'wildcard': 'WILDCARD'}
    lines = []
    for m in mini_league_data['standings']['results']:
        gw_data = m.get('gameweek_data', {}).get(str(gameweek), {})
        picks = gw_data.get('picks', [])
        starters = [p for p in picks if p['position'] <= 11]

        finished = [p for p in starters if play_status.get(p['element']) == 'finished']
        live = [p for p in starters if play_status.get(p['element']) == 'playing']
        upcoming = [p for p in starters if play_status.get(p['element']) == 'upcoming']

        # Flag players who played but got 0 pts — these are NOT "yet to play"
        zero_pts_played = [p for p in finished if player_id_to_points.get(p['element'], 0) == 0]

        parts = [f"{len(finished)}/11 played"]
        if live:
            parts.append(f"{len(live)} live now")
        if upcoming:
            names = ", ".join(player_id_to_name.get(p['element'], '?') for p in upcoming[:3])
            parts.append(f"{len(upcoming)} yet to play ({names}{'...' if len(upcoming) > 3 else ''})")
        if zero_pts_played:
            zero_names = ", ".join(player_id_to_name.get(p['element'], '?') for p in zero_pts_played[:2])
            parts.append(f"PLAYED BUT 0pts: {zero_names}")

        chip = gw_data.get('active_chip')
        chip_str = f" | CHIP: {CHIP_LABELS.get(chip, chip.upper())}" if chip else ""
        lines.append(f"- {m['entry_name']}: " + " | ".join(parts) + chip_str)

    if not lines:
        return ""
    return "\n=== SQUAD PLAY STATUS (critical: do not assume 0pts = not played) ===\n" + "\n".join(lines)


def build_captain_context(mini_league_data: Dict, gameweek: int, players_data: List,
                          player_id_to_name: Dict, player_id_to_points: Dict,
                          play_status: Dict = None) -> str:
    """Who captained whom + their real GW return and play status.
    Status is critical — never mock a captain who hasn't kicked off yet."""
    if not players_data:
        return ""
    by_id = {p['id']: p for p in players_data}
    lines = []
    for m in mini_league_data['standings']['results']:
        picks = m.get('gameweek_data', {}).get(str(gameweek), {}).get('picks', [])
        cap = next((p for p in picks if p.get('is_captain')), None)
        if not cap:
            continue
        pid = cap['element']
        el = by_id.get(pid, {})
        name = player_id_to_name.get(pid, 'Unknown')
        gw_pts = player_id_to_points.get(pid, 0)
        season_pts = el.get('total_points', 0)
        form = el.get('form', '?')
        if play_status:
            status = play_status.get(pid, 'upcoming')
            status_label = {
                'finished': 'FINISHED - return is final',
                'playing': 'CURRENTLY PLAYING - points may change',
                'upcoming': 'HAS NOT PLAYED YET - do NOT judge this pick'
            }.get(status, 'UNKNOWN')
        else:
            status_label = 'STATUS UNKNOWN'
        lines.append(
            f"- {m['entry_name']} captained {name} [{status_label}] "
            f"(GW return so far: {gw_pts}pts | season: {season_pts}pts | form: {form})"
        )
    if not lines:
        return ""
    return "\n=== CAPTAIN PICKS ===\n" + "\n".join(lines)


def build_full_standings_for_ai(gw_standings: List, mini_league_data: Dict,
                                 play_status: Dict, player_id_to_name: Dict,
                                 player_id_to_points: Dict, gameweek: int) -> str:
    """Complete ranked GW standings table — AI must only use names/numbers from here."""
    managers = mini_league_data['standings']['results']
    overall_sorted = sorted(managers, key=lambda x: x.get('total', 0), reverse=True)
    overall_rank_map = {m['entry_name']: i + 1 for i, m in enumerate(overall_sorted)}
    by_name = {m['entry_name']: m for m in managers}

    gw_avg = (sum(e.get('GW Points', e.get('points', 0)) for e in gw_standings) /
               len(gw_standings)) if gw_standings else 0

    lines = [f"(GW avg: {gw_avg:.0f}pts)"]
    for rank, entry in enumerate(gw_standings, 1):
        name = entry.get('manager', entry.get('Team Name', '?'))
        gw_pts = entry.get('GW Points', entry.get('points', 0))
        m_data = by_name.get(name, {})
        season_total = m_data.get('total', 0)
        overall_r = overall_rank_map.get(name, '?')
        above_below = f"(+{gw_pts - gw_avg:.0f})" if gw_pts >= gw_avg else f"({gw_pts - gw_avg:.0f})"

        picks = m_data.get('gameweek_data', {}).get(str(gameweek), {}).get('picks', [])
        cap = next((p for p in picks if p.get('is_captain')), None)
        if cap:
            cap_name = player_id_to_name.get(cap['element'], '?')
            cap_pts = player_id_to_points.get(cap['element'], 0)
            cap_status = (play_status or {}).get(cap['element'], 'upcoming')
            cap_label = {'finished': '✓', 'playing': '⚡', 'upcoming': '⏳'}.get(cap_status, '?')
            cap_str = f"C: {cap_name}{cap_label}({cap_pts}pts)"
        else:
            cap_str = "C: none"

        lines.append(
            f"#{rank}. {name} | {gw_pts}pts {above_below} | "
            f"Season: {season_total}pts (#{overall_r} overall) | {cap_str}"
        )
    return "=== FULL GW STANDINGS ===\n" + "\n".join(lines)


def build_league_captaincy_trends(mini_league_data: Dict, gameweek: int,
                                   player_id_to_name: Dict, player_id_to_points: Dict,
                                   play_status: Dict = None) -> str:
    """Captain frequency + chip usage across the league this GW."""
    managers = mini_league_data['standings']['results']
    cap_counts: Dict = {}
    chips_used = []

    for m in managers:
        gw_data = m.get('gameweek_data', {}).get(str(gameweek), {})
        picks = gw_data.get('picks', [])
        cap = next((p for p in picks if p.get('is_captain')), None)
        if cap:
            pid = cap['element']
            cap_counts[pid] = cap_counts.get(pid, 0) + 1
        # active_chip is at the top level of the picks API response, not inside entry_history
        chip = gw_data.get('active_chip')
        if chip:
            chip_label = {'3xc': 'Triple Captain', 'bboost': 'Bench Boost',
                          'freehit': 'Free Hit', 'wildcard': 'Wildcard'}.get(chip, chip)
            chips_used.append(f"{m['entry_name']} ({chip_label})")

    lines = []
    if cap_counts:
        sorted_caps = sorted(cap_counts.items(), key=lambda x: x[1], reverse=True)
        top = [f"{player_id_to_name.get(pid, '?')} captained by {cnt}/{len(managers)}"
               for pid, cnt in sorted_caps[:4]]
        lines.append("Captaincy: " + " | ".join(top))
    if chips_used:
        lines.append("Chips: " + ", ".join(chips_used))

    if not lines:
        return ""
    return "\n=== LEAGUE TRENDS ===\n" + "\n".join(lines)


def build_rivalry_context(mini_league_data: Dict, gameweek: int,
                           current_scores: List) -> str:
    """Closest overall points gaps + who moved up/down this GW."""
    managers = mini_league_data['standings']['results']
    overall = sorted(managers, key=lambda x: x.get('total', 0), reverse=True)

    gaps = []
    for i in range(min(len(overall) - 1, 6)):
        a, b = overall[i], overall[i + 1]
        gap = a.get('total', 0) - b.get('total', 0)
        gaps.append(f"{a['entry_name']} leads {b['entry_name']} by only {gap}pts" if gap <= 10
                    else f"{a['entry_name']} +{gap} ahead of {b['entry_name']}")

    score_map = {s.get('manager'): s.get('points', 0) for s in current_scores}
    moves = []
    for m in managers:
        name = m['entry_name']
        curr_r = m.get('rank', 0)
        gw_pts = score_map.get(name, 0)
        prev_total = m.get('total', 0) - gw_pts
        if prev_total < 0:
            continue
        prev_rank_list = sorted(
            managers,
            key=lambda x: x.get('total', 0) - score_map.get(x['entry_name'], 0),
            reverse=True
        )
        prev_r = next((i + 1 for i, x in enumerate(prev_rank_list)
                       if x['entry_name'] == name), curr_r)
        delta = prev_r - curr_r
        if delta >= 2:
            moves.append(f"{name} climbed {delta} spots")
        elif delta <= -2:
            moves.append(f"{name} fell {abs(delta)} spots")

    out = "\n=== RIVALRIES & MOVES ==="
    if gaps:
        out += "\n" + " | ".join(gaps[:4])
    if moves:
        out += "\nThis GW: " + " | ".join(moves[:5])
    return out if (gaps or moves) else ""


def build_bench_season_leaderboard(mini_league_data: Dict, gameweek: int) -> str:
    """Season cumulative bench points — the unlucky leaderboard."""
    managers = mini_league_data['standings']['results']
    totals = []
    for m in managers:
        total = sum(h.get('points_on_bench', 0) for h in m.get('history', {}).get('current', []))
        this_gw = (m.get('gameweek_data', {}).get(str(gameweek), {})
                    .get('entry_history', {}).get('points_on_bench', 0))
        totals.append((m['entry_name'], total, this_gw))
    totals.sort(key=lambda x: x[1], reverse=True)
    if not totals:
        return ""
    lines = [f"{n}: {t}pts benched all season (+{g} this GW)" for n, t, g in totals[:5]]
    return "\n=== BENCH PAIN LEADERBOARD (season total) ===\n" + "\n".join(lines)


def build_power_rankings(mini_league_data: Dict, gameweek: int,
                          current_scores: List) -> str:
    """Form-weighted power ranking: 60% last-3 avg + 40% season avg."""
    managers = mini_league_data['standings']['results']
    overall = sorted(managers, key=lambda x: x.get('total', 0), reverse=True)
    overall_rank_map = {m['entry_name']: i + 1 for i, m in enumerate(overall)}

    power = []
    for m in managers:
        history = m.get('history', {}).get('current', [])
        if not history:
            continue
        name = m['entry_name']
        net_pts = [h['points'] - h.get('event_transfers_cost', 0) for h in history]
        season_avg = sum(net_pts) / len(net_pts)
        recent = net_pts[-3:] if len(net_pts) >= 3 else net_pts
        recent_avg = sum(recent) / len(recent)
        score = round(0.6 * recent_avg + 0.4 * season_avg, 1)
        power.append((name, score, overall_rank_map.get(name, 99)))

    power.sort(key=lambda x: x[1], reverse=True)
    if not power:
        return ""
    lines = []
    for pr, (name, score, overall_r) in enumerate(power[:8], 1):
        diff = overall_r - pr
        tag = f" ▲{diff}" if diff >= 2 else (f" ▼{abs(diff)}" if diff <= -2 else "")
        lines.append(f"#{pr} {name} ({score}pts avg){tag}")
    return "\n=== POWER RANKINGS (form-weighted) ===\n" + "\n".join(lines)


def fetch_player_gw_history(player_id: int) -> Dict[int, int]:
    """Returns {round: total_points} for a player's GW history."""
    url = BASE_URL + f"element-summary/{player_id}/"
    data = fetch_data(url)
    if not data:
        return {}
    return {h['round']: h.get('total_points', 0) for h in data.get('history', [])}


def compute_captaincy_regret(mini_league_data: Dict, gameweek: int,
                              player_id_to_points: Dict, player_id_to_name: Dict,
                              play_status: Dict = None) -> List[Dict]:
    """Best possible captain from own squad vs actual captain (finished players only)."""
    results = []
    for m in mini_league_data['standings']['results']:
        picks = m.get('gameweek_data', {}).get(str(gameweek), {}).get('picks', [])
        if not picks:
            continue
        cap_pick = next((p for p in picks if p.get('is_captain')), None)
        if not cap_pick:
            continue

        actual_id = cap_pick['element']
        multiplier = cap_pick.get('multiplier', 2)
        actual_base = player_id_to_points.get(actual_id, 0)
        actual_pts = actual_base * multiplier
        actual_name = player_id_to_name.get(actual_id, '?')
        actual_status = (play_status or {}).get(actual_id, 'upcoming')

        finished_picks = [p for p in picks
                          if (play_status or {}).get(p['element'], 'upcoming') == 'finished']

        if not finished_picks:
            results.append({'manager': m['entry_name'], 'actual_captain': actual_name,
                            'actual_pts': actual_pts, 'best_captain': 'TBD',
                            'best_pts': 0, 'regret': 0, 'is_same': False, 'pending': True})
            continue

        best_pick = max(finished_picks, key=lambda p: player_id_to_points.get(p['element'], 0))
        best_id = best_pick['element']
        best_pts = player_id_to_points.get(best_id, 0) * 2
        best_name = player_id_to_name.get(best_id, '?')
        regret = best_pts - actual_pts if actual_status == 'finished' else 0

        results.append({'manager': m['entry_name'], 'actual_captain': actual_name,
                        'actual_pts': actual_pts, 'actual_status': actual_status,
                        'best_captain': best_name, 'best_pts': best_pts,
                        'regret': regret, 'is_same': actual_id == best_id, 'pending': False})

    return sorted(results, key=lambda x: x['regret'], reverse=True)


def compute_luck_score(mini_league_data: Dict, gameweek: int,
                       players_data: List, player_id_to_points: Dict) -> List[Dict]:
    """Actual GW pts vs FPL expected pts (ep_this) for each manager's starting XI."""
    ep_map = {p['id']: float(p.get('ep_this') or 0) for p in players_data}
    results = []
    for m in mini_league_data['standings']['results']:
        picks = m.get('gameweek_data', {}).get(str(gameweek), {}).get('picks', [])
        starters = [p for p in picks if p['position'] <= 11]
        if not starters:
            continue
        expected = sum(ep_map.get(p['element'], 0) * p.get('multiplier', 1) for p in starters)
        actual = sum(player_id_to_points.get(p['element'], 0) * p.get('multiplier', 1) for p in starters)
        results.append({'manager': m['entry_name'], 'expected': round(expected, 1),
                        'actual': actual, 'luck': round(actual - expected, 1)})
    return sorted(results, key=lambda x: x['luck'], reverse=True)


def compute_transfer_regret(mini_league_data: Dict, gameweek: int,
                             player_id_to_name: Dict) -> List[Dict]:
    """For each past transfer, compare player OUT vs IN over 3 GWs after transfer."""
    managers = mini_league_data['standings']['results']
    all_past_transfers = [t for m in managers for t in m.get('transfers', [])
                          if t['event'] < gameweek]
    if not all_past_transfers:
        return [{'manager': m['entry_name'], 'total_regret': 0, 'worst': None, 'details': []} for m in managers]

    unique_pids = {t['element_out'] for t in all_past_transfers} | {t['element_in'] for t in all_past_transfers}
    player_history: Dict[int, Dict[int, int]] = {}
    for pid in unique_pids:
        player_history[pid] = fetch_player_gw_history(pid)

    results = []
    for m in managers:
        name = m['entry_name']
        past_transfers = [t for t in m.get('transfers', []) if t['event'] < gameweek]
        if not past_transfers:
            results.append({'manager': name, 'total_regret': 0, 'worst': None, 'details': []})
            continue

        details = []
        for t in past_transfers:
            gw_out = t['event']
            window = list(range(gw_out + 1, min(gw_out + 4, gameweek + 1)))
            out_pts = sum(player_history.get(t['element_out'], {}).get(g, 0) for g in window)
            in_pts = sum(player_history.get(t['element_in'], {}).get(g, 0) for g in window)
            regret = out_pts - in_pts
            details.append({'gw': gw_out,
                            'out': player_id_to_name.get(t['element_out'], '?'),
                            'in': player_id_to_name.get(t['element_in'], '?'),
                            'out_pts': out_pts, 'in_pts': in_pts, 'regret': regret,
                            'window_gws': len(window)})

        details.sort(key=lambda x: x['regret'], reverse=True)
        total_regret = sum(d['regret'] for d in details)
        results.append({'manager': name, 'total_regret': total_regret,
                        'worst': details[0] if details else None, 'details': details})

    return sorted(results, key=lambda x: x['total_regret'], reverse=True)


def compute_manager_archetypes(mini_league_data: Dict, gameweek: int) -> Dict[str, Dict]:
    """Assign each manager their most extreme archetype label based on season stats."""
    import statistics
    managers = mini_league_data['standings']['results']
    total = len(managers)

    raw: Dict[str, Dict] = {}
    for m in managers:
        name = m['entry_name']
        history = m.get('history', {}).get('current', [])
        chips = m.get('history', {}).get('chips', [])
        picks = m.get('gameweek_data', {}).get(str(gameweek), {}).get('picks', [])
        transfers = m.get('transfers', [])
        my_pids = {p['element'] for p in picks}

        total_hits = sum(h.get('event_transfers_cost', 0) for h in history)
        total_bench = sum(h.get('points_on_bench', 0) for h in history)

        overlaps = []
        for other in managers:
            if other['entry_name'] == name:
                continue
            other_pids = {p['element'] for p in other.get('gameweek_data', {}).get(str(gameweek), {}).get('picks', [])}
            overlaps.append(len(my_pids & other_pids))
        avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0

        cap_pick = next((p for p in picks if p.get('is_captain')), None)
        cap_uniqueness = 0
        if cap_pick:
            cap_pid = cap_pick['element']
            cap_count = sum(
                1 for other in managers
                if any(p.get('is_captain') and p['element'] == cap_pid
                       for p in other.get('gameweek_data', {}).get(str(gameweek), {}).get('picks', []))
            )
            cap_uniqueness = total - cap_count

        wc_chip = next((c for c in chips if c['name'] in ('wildcard', 'freehit')), None)
        wc_regret = 0
        if wc_chip:
            wc_gw = wc_chip['event']
            all_gw_scores = [h['points'] - h.get('event_transfers_cost', 0)
                             for other in managers
                             for h in other.get('history', {}).get('current', [])
                             if h['event'] == wc_gw]
            league_avg_wc = sum(all_gw_scores) / len(all_gw_scores) if all_gw_scores else 50
            my_wc_score = next((h['points'] - h.get('event_transfers_cost', 0)
                                for h in history if h['event'] == wc_gw), league_avg_wc)
            wc_regret = max(0, league_avg_wc - my_wc_score)

        net_pts_list = [h['points'] - h.get('event_transfers_cost', 0) for h in history]
        volatility = statistics.stdev(net_pts_list) if len(net_pts_list) >= 2 else 0

        num_transfers = len(transfers)
        ironman_score = -num_transfers

        first_rank = history[0].get('overall_rank', 0) if history else 0
        latest_rank = history[-1].get('overall_rank', 0) if history else 0
        rank_improvement = first_rank - latest_rank

        raw[name] = {
            'The Hit Addict': total_hits,
            'The Bench Hoarder': total_bench,
            'The Template Merchant': avg_overlap,
            'The Captain Contrarian': cap_uniqueness,
            'The Wildcard Waster': wc_regret,
            'The Streaky Scorer': volatility,
            'The Ironman': ironman_score,
            'The Comeback Kid': rank_improvement,
        }

    archetypes_list = list(raw[managers[0]['entry_name']].keys())
    norm: Dict[str, Dict] = {m['entry_name']: {} for m in managers}
    for archetype in archetypes_list:
        vals = [raw[m['entry_name']][archetype] for m in managers]
        mn, mx = min(vals), max(vals)
        rng = mx - mn if mx != mn else 1
        for m in managers:
            name = m['entry_name']
            norm[name][archetype] = (raw[name][archetype] - mn) / rng

    result = {}
    reasons = {
        'The Hit Addict': lambda m, r: f"{r['The Hit Addict']:.0f}pts in transfer hits",
        'The Bench Hoarder': lambda m, r: f"{r['The Bench Hoarder']:.0f}pts left on bench this season",
        'The Template Merchant': lambda m, r: f"avg {r['The Template Merchant']:.1f} squad overlaps with the league",
        'The Captain Contrarian': lambda m, r: f"captained a player owned by {max(1, total - int(r['The Captain Contrarian']))} others",
        'The Wildcard Waster': lambda m, r: f"used chip in a below-avg GW",
        'The Streaky Scorer': lambda m, r: f"highest score variance in the league",
        'The Ironman': lambda m, r: f"barely touches the squad",
        'The Comeback Kid': lambda m, r: f"biggest rank improvement this season",
    }
    for m in managers:
        name = m['entry_name']
        best_archetype = max(norm[name].items(), key=lambda x: x[1])[0]
        raw_val = raw[name]
        try:
            reason = reasons[best_archetype](name, raw_val)
        except Exception:
            reason = best_archetype
        result[name] = {'label': best_archetype, 'reason': reason}

    return result


def build_captaincy_regret_context(regret_data: List[Dict]) -> str:
    if not regret_data:
        return ""
    lines = []
    for r in regret_data:
        if r.get('pending'):
            lines.append(f"- {r['manager']}: captain {r['actual_captain']} yet to play — regret TBD")
        elif r['is_same']:
            lines.append(f"- {r['manager']}: nailed it — {r['actual_captain']} was the right call ({r['actual_pts']}pts)")
        else:
            lines.append(f"- {r['manager']}: captained {r['actual_captain']} ({r['actual_pts']}pts) | "
                         f"best pick was {r['best_captain']} ({r['best_pts']}pts) | "
                         f"regret: {r['regret']:+d}pts")
    return "\n=== CAPTAINCY REGRET ===\n" + "\n".join(lines)


def build_luck_score_context(luck_data: List[Dict]) -> str:
    if not luck_data:
        return ""
    lines = []
    for ld in luck_data:
        sign = "+" if ld['luck'] >= 0 else ""
        label = "LUCKY" if ld['luck'] > 5 else ("UNLUCKY" if ld['luck'] < -5 else "on track")
        lines.append(f"- {ld['manager']}: expected {ld['expected']}pts, got {ld['actual']}pts "
                     f"({sign}{ld['luck']} luck) [{label}]")
    return "\n=== LUCK SCORES (xPts vs actual) ===\n" + "\n".join(lines)


def build_transfer_regret_context(regret_data: List[Dict]) -> str:
    if not regret_data:
        return ""
    lines = []
    for r in regret_data:
        if r['total_regret'] == 0 and r['worst'] is None:
            lines.append(f"- {r['manager']}: no past transfers yet")
            continue
        worst = r['worst']
        if worst and worst['regret'] > 0:
            lines.append(f"- {r['manager']}: season transfer regret {r['total_regret']:+d}pts | "
                         f"worst: sold {worst['out']} for {worst['in']} in GW{worst['gw']} "
                         f"({worst['out']} got {worst['out_pts']}pts vs {worst['in']} {worst['in_pts']}pts "
                         f"over next {worst['window_gws']} GWs = {worst['regret']:+d}pts regret)")
        else:
            lines.append(f"- {r['manager']}: transfer regret {r['total_regret']:+d}pts (net positive)")
    return "\n=== TRANSFER REGRET (3-GW window) ===\n" + "\n".join(lines[:8])


def build_archetypes_context(archetypes: Dict[str, Dict]) -> str:
    if not archetypes:
        return ""
    lines = [f"- {name}: {data['label']} ({data['reason']})"
             for name, data in archetypes.items()]
    return "\n=== MANAGER ARCHETYPES ===\n" + "\n".join(lines)


def build_points_left_on_table(mini_league_data: Dict, gameweek: int,
                                regret_data: List[Dict], luck_data: List[Dict]) -> str:
    """Per-manager GW self-destruction: bench waste + captain miss + transfer cost."""
    managers = mini_league_data['standings']['results']
    regret_map = {r['manager']: r.get('regret', 0) for r in regret_data}
    rows = []
    for m in managers:
        name = m['entry_name']
        gw_data = m.get('gameweek_data', {}).get(str(gameweek), {})
        entry_history = gw_data.get('entry_history', {})
        bench_pts = entry_history.get('points_on_bench', 0)
        transfer_cost = entry_history.get('event_transfers_cost', 0)
        cap_miss = max(0, regret_map.get(name, 0))
        total_lost = bench_pts + cap_miss + transfer_cost
        rows.append({'manager': name, 'bench': bench_pts, 'cap_miss': cap_miss,
                     'hit': transfer_cost, 'total': total_lost})

    rows.sort(key=lambda x: x['total'], reverse=True)
    if not rows:
        return ""
    lines = []
    for r in rows:
        parts = []
        if r['bench']:
            parts.append(f"{r['bench']}pts benched")
        if r['cap_miss']:
            parts.append(f"{r['cap_miss']}pts captain miss")
        if r['hit']:
            parts.append(f"{r['hit']}pts hit")
        detail = " + ".join(parts) if parts else "clean week"
        lines.append(f"- {r['manager']}: {r['total']}pts left on table ({detail})")
    return "\n=== POINTS LEFT ON TABLE (this GW) ===\n" + "\n".join(lines)


def generate_ai_insights(mini_league_data: Dict, gameweek: int, current_scores: List,
                         player_id_to_name: Dict = None, player_id_to_points: Dict = None,
                         is_final: bool = False, gw_status: Dict = None,
                         play_status: Dict = None, players_data: List = None,
                         extra_context: str = "") -> str:
    """Generate AI-powered insights using OpenAI API with rich historical and player context."""
    if not OPENAI_AVAILABLE:
        return None
        
    try:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logger.warning("OPENAI_API_KEY not found, skipping AI insights")
            return None
        
        client = OpenAI(api_key=api_key)
        
        # Gather rich insights data (now play_status-aware)
        data = gather_rich_insights_data(mini_league_data, gameweek, current_scores,
                                         player_id_to_name, player_id_to_points,
                                         play_status=play_status)

        if gw_status is None:
            gw_status = get_gameweek_status(gameweek)

        data['is_final'] = is_final or gw_status.get('is_finished', False)
        data['gw_status'] = gw_status
        is_final = data['is_final']
        fixtures_finished = gw_status.get('fixtures_finished', 0)
        fixtures_remaining = gw_status.get('fixtures_remaining', 0)
        total_fixtures = gw_status.get('total_fixtures', 10)
        fixtures_in_progress = gw_status.get('fixtures_in_progress', 0)
        fixtures_not_started = gw_status.get('fixtures_not_started',
                                              total_fixtures - fixtures_finished - fixtures_in_progress)

        # ------------------------------------------------------------------ #
        # Build the data grounding block — the AI MUST only use names/numbers
        # from here. Full table prevents hallucination of scores and names.
        # ------------------------------------------------------------------ #
        gw_sorted = sorted(current_scores,
                           key=lambda x: x.get('points', x.get('net_points', 0)),
                           reverse=True)

        # Convert current_scores structure to match what build_full_standings_for_ai expects
        gw_standings_for_ai = [
            {'manager': s['manager'], 'GW Points': s.get('points', 0),
             'Team Name': s['manager']}
            for s in gw_sorted
        ]

        full_table = build_full_standings_for_ai(
            gw_standings_for_ai, mini_league_data,
            play_status or {}, player_id_to_name or {},
            player_id_to_points or {}, gameweek
        )
        captain_ctx = build_captain_context(
            mini_league_data, gameweek, players_data or [],
            player_id_to_name or {}, player_id_to_points or {},
            play_status=play_status
        )
        captaincy_trends = build_league_captaincy_trends(
            mini_league_data, gameweek,
            player_id_to_name or {}, player_id_to_points or {},
            play_status=play_status
        )
        rivalry_ctx = build_rivalry_context(mini_league_data, gameweek, current_scores)
        bench_ctx = build_bench_season_leaderboard(mini_league_data, gameweek)
        power_ctx = build_power_rankings(mini_league_data, gameweek, current_scores)
        ytp_ctx = build_yet_to_play_context(
            mini_league_data, gameweek, play_status,
            player_id_to_name or {}, player_id_to_points or {}
        )
        squad_status_ctx = build_squad_play_status_context(
            mini_league_data, gameweek, play_status or {},
            player_id_to_name or {}, player_id_to_points or {}
        )

        # Extra spicy facts if available
        extra_facts = []
        if data.get('hit_takers'):
            for h in data['hit_takers'][:3]:
                extra_facts.append(f"{h['manager']} took a -{h['hit_cost']}pt hit "
                                   f"(gross: {h['gross_points']}pts, net: {h['net_points']}pts)")
        if data.get('most_bench_points') and data['most_bench_points']['bench_points'] >= 8:
            mb = data['most_bench_points']
            extra_facts.append(f"{mb['manager']} left {mb['bench_points']}pts rotting on the bench")
        if data.get('transfer_heroes'):
            th = data['transfer_heroes'][0]
            xf = th['transfers'][0] if th.get('transfers') else 'a transfer'
            extra_facts.append(f"{th['manager']} nailed {xf} for +{th['net_effect']}pts net gain")
        if data.get('transfer_villains'):
            tv = data['transfer_villains'][0]
            xf = tv['transfers'][0] if tv.get('transfers') else 'a transfer'
            extra_facts.append(f"{tv['manager']} regrets {xf} ({tv['net_effect']}pts swing)")
        for rec in data.get('records', [])[:2]:
            if rec['type'] == 'season_high':
                extra_facts.append(f"{rec['manager']} just set a new personal season best: {rec['points']}pts")
            elif rec['type'] == 'season_low' and gameweek > 1:
                extra_facts.append(f"{rec['manager']} hit their season low this week: {rec['points']}pts")
        if data.get('hottest_form') and data['hottest_form']['form_diff'] > 3:
            hf = data['hottest_form']
            extra_facts.append(f"{hf['manager']} is on fire — last 5 avg {hf['last_5_avg']}pts vs "
                               f"season avg {hf['season_avg']}pts")
        if data.get('biggest_climber') and data['biggest_climber']['change'] >= 2:
            bc = data['biggest_climber']
            extra_facts.append(f"{bc['manager']} jumped {bc['change']} league spots this GW")
        if data.get('biggest_faller') and data['biggest_faller']['change'] <= -2:
            bf = data['biggest_faller']
            extra_facts.append(f"{bf['manager']} crashed {abs(bf['change'])} league spots this GW")

        # Status framing
        if is_final:
            status_line = f"GW{gameweek} FINAL — all {total_fixtures} fixtures done."
            task = (
                f"Write a FINAL match report for GW{gameweek} — structured EXACTLY as follows:\n\n"
                "HEADLINE (1 sentence, all-caps, punchy and specific to this GW's biggest story)\n\n"
                "THE STORY (5-6 paragraphs, ~350 words total): This is the centrepiece — write it like a "
                "real sports journalist covering a match. Tell the story of the WHOLE gameweek:\n"
                "  Para 1 — How GW opened: who was leading early, which captains looked smart on Friday/Saturday, "
                "what the early mood in the league was.\n"
                "  Para 2 — The mid-week swing: which results changed everything, which managers were climbing "
                "or crashing as fixtures ticked off. Name actual players and their hauls.\n"
                "  Para 3 — The decisive moments: the captain call that won the week, the bench disaster that "
                "cost someone, the differential pick that nobody saw coming. Be specific — real player names, "
                "real points.\n"
                "  Para 4 — Where it left the OVERALL standings: who is making a title charge, who is in danger "
                "at the bottom, which rivalries are heating up. Reference the previous week's winner if relevant.\n"
                "  Para 5/6 — Context and patterns: call out recurring themes (managers who always blank on "
                "captains, serial bench wasters, the overachiever on form). Make it feel like you know these "
                "people across the whole season, not just this week.\n\n"
                "MANAGER VERDICTS (one line per manager, cover ALL managers in the league): "
                "Format exactly as: [FIRST NAME]: [verdict]. One punchy sentence each — be specific about "
                "what they did THIS week (captain pick, a transfer, bench pts, rank change). Alternate tone: "
                "some glowing praise, some gentle roasting, none bland.\n\n"
                "NEXT WEEK TEASER (1 punchy sentence teasing the GW{gw_next} storylines).\n\n"
                "Total output: 500-600 words. FINAL results — be completely definitive and confident."
            ).replace("{gw_next}", str(gameweek + 1))
        else:
            # Spell out the fixture state in plain English so the AI can't misread it
            if fixtures_finished == 0 and fixtures_in_progress == 0:
                fixture_state = (f"NO fixtures have finished yet — GW{gameweek} has not really started. "
                                 f"All {total_fixtures} games are still to come.")
            elif fixtures_finished == 0 and fixtures_in_progress > 0:
                fixture_state = (f"{fixtures_in_progress} fixture(s) are CURRENTLY IN PROGRESS "
                                 f"but ZERO have finished. {fixtures_not_started} more yet to kick off. "
                                 f"Scores are completely provisional — nothing is settled.")
            else:
                fixture_state = (f"{fixtures_finished} of {total_fixtures} fixtures have FINISHED. "
                                 f"{fixtures_in_progress} currently in progress. "
                                 f"{fixtures_not_started} still to kick off (not started yet).")
            status_line = (
                f"GW{gameweek} IN PROGRESS — {fixture_state} "
                f"STANDINGS ARE PROVISIONAL AND WILL CHANGE."
            )
            task = (
                f"Write a LIVE match-day update for GW{gameweek} — structured EXACTLY as follows:\n\n"
                "HEADLINE (1 sentence, all-caps, captures the drama so far)\n\n"
                "THE STORY (5-6 paragraphs, ~350 words): Tell the story of the gameweek SO FAR:\n"
                f"  Para 1 — How GW{gameweek} opened: who looked sharp in early fixtures, which captains "
                "were already paying off or bombing.\n"
                "  Para 2 — The mid-week picture: who is leading right now and why, which results changed things.\n"
                "  Para 3 — Biggest storylines: a key captain pick, a differential that's working, a disaster in progress.\n"
                "  Para 4 — Overall league context: how this GW is shifting the season standings, who needs a "
                "big finish and who can afford to coast.\n"
                "  Para 5 — The suspense: what's still to come, which managers have their key players yet to play, "
                "and what could still flip the result.\n"
                f"Be honest that {fixtures_not_started} fixture(s) remain and nothing is decided. "
                "IMPORTANT: 0pts may mean ALREADY PLAYED AND BLANKED — check squad play status. "
                "Build genuine suspense without declaring winners.\n\n"
                "MANAGER VERDICTS (one line per manager, cover ALL managers in the league): "
                "Format exactly as: [FIRST NAME]: [verdict]. Be specific about what they've done so far. "
                "Flag managers with key players still to play — use 'watch this space' energy.\n\n"
                "SUSPENSE CLOSER (1 sentence about the biggest unanswered question).\n\n"
                "Total output: 500-600 words. Do NOT declare final winners."
            )

        all_ctx = "\n\n".join(filter(None, [
            full_table, squad_status_ctx, captain_ctx, captaincy_trends, rivalry_ctx,
            power_ctx, bench_ctx, ytp_ctx, extra_context,
            ("EXTRA STORY ANGLES:\n" + "\n".join(f"- {f}" for f in extra_facts)) if extra_facts else ""
        ]))

        # All valid manager first names (so AI knows who exists in this league)
        valid_names = ", ".join(
            m['entry_name'].split()[0]
            for m in mini_league_data['standings']['results']
        )

        prompt = f"""{status_line}

{all_ctx}

VALID FIRST NAMES IN THIS LEAGUE: {valid_names}

YOUR TASK: {task}

ABSOLUTE RULES — breaking any of these makes the output worthless:
1. ONLY use manager names and football player names that appear in the data above. Zero invention.
2. Every point figure you state must match the table exactly.
3. Captains with [HAS NOT PLAYED YET] or [CURRENTLY PLAYING] must NOT be called flops or failures — their story isn't written yet. You may tease "watch this space".
4. NET points (after hit deductions) are the official score. If someone took a hit, note it.
5. No emojis, no markdown (**bold** etc), plain text only, CAPS for emphasis.

TONE: You are the funniest, most insightful person in a WhatsApp group of football obsessives who've been playing together for years. You know their habits, their recurring disasters, their lucky streaks. Warm roasting and genuine praise in equal measure. First-name basis. Reference ACTUAL captain picks, real player names, actual transfer decisions. Every manager verdict must be SPECIFIC — not generic. No manager should feel ignored."""

        logger.info(f"Calling OpenAI API with prompt length: {len(prompt)}")

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "You are the sharp, funny match correspondent for a tight-knit FPL mini-league group chat. "
                    "Your job: write reports that feel PERSONAL — like they were written by someone who has "
                    "watched every single one of these managers suffer and celebrate across the whole season. "
                    "You are data-driven but never dry. You reward bold calls and skewer costly mistakes with "
                    "affection, not cruelty. You use league history and context — not just this week's scores — "
                    "to make each verdict feel earned. "
                    f"{'This is the FINAL result — be completely definitive and decisive.' if is_final else f'This is a LIVE update with {fixtures_remaining} fixtures remaining — stay dramatic and provisional.'} "
                    "Structure your output exactly as the task instructs. Plain text only. CAPS for emphasis. "
                    "No emojis. No markdown formatting."
                )},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1400,
            temperature=0.88
        )
        
        logger.info(f"OpenAI API response received. Choices count: {len(response.choices)}")
        
        if not response.choices or len(response.choices) == 0:
            logger.error("No choices in OpenAI response")
            return None
        
        if not hasattr(response.choices[0], 'message') or not response.choices[0].message:
            logger.error("No message in OpenAI response choice")
            return None
        
        insights = response.choices[0].message.content
        if insights:
            insights = insights.strip()
            print(f"================================================")
            print(f"AI insights generated: {insights}")
            print(f"================================================")
            logger.info(f"AI insights generated successfully: {len(insights)} characters")
            return insights
        else:
            logger.warning("AI insights content is None or empty")
            return None
        
    except Exception as e:
        logger.error(f"Error generating AI insights: {e}")
        import traceback
        logger.error(traceback.format_exc())
        print(f"ERROR in generate_ai_insights: {e}")
        return None

def plot_gw_vs_overall_analysis(mini_league_data: Dict, gameweek: int, current_scores: List, 
                                fun_facts: Dict, ai_insights: str, num: int) -> None:
    """Create a visualization showing current GW performance vs overall performance."""
    fig = plt.figure(figsize=(16, 12), facecolor='white')
    gs = fig.add_gridspec(3, 2, height_ratios=[0.2, 1, 1], hspace=0.4, wspace=0.3)
    
    # Title (AI insights removed - only shown in message)
    ax_title = fig.add_subplot(gs[0, :])
    ax_title.axis('off')
    ax_title.text(0.5, 0.5, f'Gameweek {gameweek} Analysis', 
                 fontsize=24, fontweight='bold', ha='center', va='center', color='#2c3e50',
                 transform=ax_title.transAxes)
    
    # Current GW vs Overall Rank comparison
    ax1 = fig.add_subplot(gs[1, 0])
    
    # Calculate overall ranks
    league_standings = sorted(mini_league_data['standings']['results'], 
                             key=lambda x: x.get('total', 0), reverse=True)
    overall_ranks = {team['entry_name']: idx + 1 
                     for idx, team in enumerate(league_standings)}
    
    # Get GW ranks
    gw_standings = sorted(current_scores, key=lambda x: x['points'], reverse=True)
    gw_ranks = {item['manager']: idx + 1 for idx, item in enumerate(gw_standings)}
    
    managers = list(overall_ranks.keys())
    overall_rank_vals = [overall_ranks[m] for m in managers]
    gw_rank_vals = [gw_ranks.get(m, len(managers)) for m in managers]
    
    x = range(len(managers))
    width = 0.35
    
    bars1 = ax1.bar([i - width/2 for i in x], overall_rank_vals, width, 
                    label='Overall Rank', color='#3498db', alpha=0.7)
    bars2 = ax1.bar([i + width/2 for i in x], gw_rank_vals, width,
                    label=f'GW{gameweek} Rank', color='#e74c3c', alpha=0.7)
    
    ax1.set_ylabel('Rank (Lower is Better)', fontsize=12, fontweight='bold')
    ax1.set_xlabel('Managers', fontsize=12, fontweight='bold')
    ax1.set_title('Overall Rank vs Current Gameweek Rank', fontsize=14, fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(managers, rotation=45, ha='right', fontsize=9)
    ax1.legend(fontsize=10)
    ax1.invert_yaxis()  # Lower rank is better
    ax1.grid(axis='y', alpha=0.3)
    
    # GW Points vs Average Points
    ax2 = fig.add_subplot(gs[1, 1])
    
    gw_points = [item['points'] for item in current_scores]
    avg_points = sum(gw_points) / len(gw_points) if gw_points else 0
    
    colors = ['#2ecc71' if p >= avg_points else '#e74c3c' for p in gw_points]
    bars = ax2.bar(managers, gw_points, color=colors, alpha=0.7, edgecolor='black', linewidth=1)
    
    # Add average line
    ax2.axhline(y=avg_points, color='gray', linestyle='--', linewidth=2, label=f'Average: {avg_points:.1f}')
    
    # Add value labels
    for bar, pts in zip(bars, gw_points):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(pts)}', ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    ax2.set_ylabel('Points', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Managers', fontsize=12, fontweight='bold')
    ax2.set_title(f'Gameweek {gameweek} Points Distribution', fontsize=14, fontweight='bold')
    ax2.set_xticks(range(len(managers)))
    ax2.set_xticklabels(managers, rotation=45, ha='right', fontsize=9)
    ax2.legend(fontsize=10)
    ax2.grid(axis='y', alpha=0.3)
    
    # Performance Trends (Bottom row)
    ax3 = fig.add_subplot(gs[2, :])
    
    # Calculate points trend (last 5 GWs vs current)
    trend_data = []
    for manager in mini_league_data['standings']['results']:
        manager_name = manager['entry_name']
        history = manager['history']['current']
        if len(history) >= 5:
            last_5_avg = np.mean([h['points'] - h.get('event_transfers_cost', 0) for h in history[-5:]])  # NET
            current_gw_points = next((item['points'] for item in current_scores 
                                    if item['manager'] == manager_name), 0)
            trend_data.append({
                'manager': manager_name,
                'last_5_avg': last_5_avg,
                'current': current_gw_points,
                'change': current_gw_points - last_5_avg
            })
    
    if trend_data:
        trend_data.sort(key=lambda x: x['change'], reverse=True)
        managers_trend = [d['manager'] for d in trend_data]
        changes = [d['change'] for d in trend_data]
        
        colors_trend = ['#2ecc71' if c > 0 else '#e74c3c' for c in changes]
        bars = ax3.barh(managers_trend, changes, color=colors_trend, alpha=0.7, edgecolor='black')
        
        # Add value labels
        for bar, change in zip(bars, changes):
            width = bar.get_width()
            ax3.text(width, bar.get_y() + bar.get_height()/2.,
                    f'{change:+.1f}', ha='left' if change > 0 else 'right',
                    va='center', fontsize=9, fontweight='bold')
        
        ax3.axvline(x=0, color='black', linestyle='-', linewidth=1)
        ax3.set_xlabel('Points Change vs Last 5 GW Average', fontsize=12, fontweight='bold')
        ax3.set_title('Performance Trend: Current GW vs Recent Form', fontsize=14, fontweight='bold')
        ax3.grid(axis='x', alpha=0.3)
    
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    
    # Save the plot
    plots_dir = create_plots_directory()
    plt.savefig(os.path.join(plots_dir, f'{num}_gw_analysis_gw{gameweek}.png'),
                dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()

def generate_pdf_report(gameweek):
    """
    Generate a PDF report with all plots while maintaining aspect ratios.
    """
    from fpdf import FPDF
    import os
    from PIL import Image
    
    # Initialize PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Add title page with interesting stats
    pdf.add_page()
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 10, f'Fantasy Premier League Analysis - Gameweek {gameweek}', ln=True, align='C')
    
    plots_dir = create_plots_directory()
    stats_file = os.path.join(plots_dir, 'interesting_stats.png')
    
    if os.path.exists(stats_file):
        # Get image dimensions
        with Image.open(stats_file) as img:
            width, height = img.size
        
        # Calculate dimensions to maintain aspect ratio
        page_width = 210
        page_margin = 20
        max_width = page_width - 2 * page_margin
        scale = max_width / width
        new_width = width * scale
        new_height = height * scale
        
        # Center the image
        x = (page_width - new_width) / 2
        pdf.image(stats_file, x=x, y=30, w=new_width)
    
    # Add remaining plots
    plot_files = [f for f in os.listdir(plots_dir) if f.endswith('.png') and f != 'interesting_stats.png']
    
    # Sort numerically by prefix number (e.g., 1_, 2_, 10_)
    def get_sort_key(filename):
        # Extract number prefix if it exists (e.g., "1_gw_analysis_gw15.png" -> 1)
        try:
            if '_' in filename:
                prefix = filename.split('_')[0]
                if prefix.isdigit():
                    return (0, int(prefix))  # Numeric prefix
            return (1, filename)  # Non-numeric, sort alphabetically
        except:
            return (1, filename)
    
    plot_files.sort(key=get_sort_key)
    
    for plot_file in plot_files:
        pdf.add_page()
        file_path = os.path.join(plots_dir, plot_file)
        
        with Image.open(file_path) as img:
            width, height = img.size
        
        # Calculate dimensions
        page_width = 210
        page_margin = 20
        max_width = page_width - 2 * page_margin
        scale = max_width / width
        new_width = width * scale
        new_height = height * scale
        x = (page_width - new_width) / 2
        
        pdf.image(file_path, x=x, y=30, w=new_width)
    
    # Save PDF
    pdf_file = os.path.join(plots_dir, f'gameweek_{gameweek}_report.pdf')
    pdf.output(pdf_file)
    print(f"PDF report generated: {pdf_file}")
    return pdf_file

def get_detailed_gw_data(manager_data, desired_gw, player_id_to_name, player_id_to_points, player_id_to_position, mini_league_data):
    gw_data_list = []

    gw_data = manager_data['gameweek_data'].get(str(desired_gw), {})
    picks = gw_data.get('picks', [])
    entry_history = gw_data.get('entry_history', {})
    gross_points = entry_history.get('points', 0)  # API returns GROSS
    transfer_cost = entry_history.get('event_transfers_cost', 0)
    gw_data['points'] = gross_points - transfer_cost  # Store NET points
    gw_data['gross_points'] = gross_points
    gw_data['rank'] = entry_history.get('rank', 0)
    gw_data['event_transfers'] = entry_history.get('event_transfers', 0)
    gw_data['event_transfers_cost'] = transfer_cost
    active_chip = gw_data.get('active_chip', "No Chip Used")

    top_scorer_id = max(picks, key=lambda x: player_id_to_points.get(x['element'], 0))['element']
    max_points = player_id_to_points.get(top_scorer_id, 0)
    top_scorer_position = next((pick['position'] for pick in picks if pick['element'] == top_scorer_id), None)
    top_scorer_played = top_scorer_position < 12 if top_scorer_position else False

    underperformer_id = min(picks, key=lambda x: player_id_to_points.get(x['element'], 0))['element']
    min_points = player_id_to_points.get(underperformer_id, 0)

    starting_players = [pick for pick in picks if pick['position'] <= 11]
    formation = "{}-{}-{}".format(
        sum(1 for pick in starting_players if player_id_to_position[pick['element']] == 2),
        sum(1 for pick in starting_players if player_id_to_position[pick['element']] == 3),
        sum(1 for pick in starting_players if player_id_to_position[pick['element']] == 4)
    )

    captain_id = next((pick['element'] for pick in picks if pick['is_captain']), None)
    captain_multiplier = next((pick['multiplier'] for pick in picks if pick['is_captain']), 1)
    vice_captain_id = next((pick['element'] for pick in picks if pick['is_vice_captain']), None)
    vice_captain_multiplier = next((pick['multiplier'] for pick in picks if pick['is_vice_captain']), 1)

    captain_name = player_id_to_name.get(captain_id, 'Unknown')
    captain_points = player_id_to_points.get(captain_id, 0) * captain_multiplier
    vice_captain_name = player_id_to_name.get(vice_captain_id, 'Unknown')
    vice_captain_points = player_id_to_points.get(vice_captain_id, 0) * vice_captain_multiplier

    defensive_points = sum(player_id_to_points[pick['element']] for pick in starting_players if player_id_to_position[pick['element']] in [1, 2])
    attacking_points = sum(player_id_to_points[pick['element']] for pick in starting_players if player_id_to_position[pick['element']] in [3, 4])

    chip_used = active_chip

    avg_points = calculate_gw_average(mini_league_data, desired_gw)
    gw_performance_vs_avg = gw_data['points'] - avg_points
    rank_movement = (manager_data.get('last_rank', 0) - manager_data.get('rank', 0))

    gw_data_list.append({
        'Gameweek': desired_gw,
        'Points': gw_data['points'],
        'Rank': gw_data['rank'],
        'Captain': captain_name,
        'Captain Points': captain_points,
        'Vice-Captain': vice_captain_name,
        'Vice-Captain Points': vice_captain_points,
        'Transfers': gw_data['event_transfers'],
        'Transfer Cost': gw_data['event_transfers_cost'],
        'Team Value': entry_history.get('value', 0) / 10,
        'Points on Bench': entry_history.get('points_on_bench', 0),
        'Bank Money': entry_history.get('bank', 0) / 10,
        'Top Scorer': player_id_to_name.get(top_scorer_id, 'Unknown'),
        'Top Scorer Points': max_points,
        'Top Scorer Played': top_scorer_played,
        'Underperformer': player_id_to_name.get(underperformer_id, 'Unknown'),
        'Underperformer Points': min_points,
        'Formation': formation,
        'Defensive Points': defensive_points,
        'Attacking Points': attacking_points,
        'Chip Used': chip_used,
        'Performance vs Avg': gw_performance_vs_avg,
        'Rank Movement': rank_movement
    })

    return gw_data_list

def main(args):
    # FPL mini-league id. Priority: --lid arg > FANTASY_GROUP_ID env > default.
    # NOTE: FANTASY_GROUP_ID currently holds the FPL league id (348645,
    # "Pullman Football Samaj"). The Facebook Messenger thread should get its
    # own variable before re-enabling the FB sender.
    league_id = args.lid or int(os.getenv('FANTASY_GROUP_ID') or 348645)
    logger.info(f"Using FPL league id: {league_id}")
    is_final = args.final
    gameweek = int(args.gw)

    player_data_folder = os.path.join(local_path, "player_data")
    league_data_folder = os.path.join(local_path, "league_data")
    
    os.makedirs(player_data_folder, exist_ok=True)
    os.makedirs(league_data_folder, exist_ok=True)

    mini_league_file = f"league_data/mini_league_data_gw{gameweek}.json"
    player_data_file = f"player_data/players_data_gw{gameweek}.json"
    mini_league_file = os.path.join(local_path, mini_league_file)
    player_data_file = os.path.join(local_path, player_data_file)

    # Always fetch new data with live points
    mini_league_data = retrieve_mini_league_data(int(league_id), int(gameweek))
    save_to_json(mini_league_data, mini_league_file)

    player_data = fetch_bootstrap_data()
    save_to_json(player_data, player_data_file)

    # Fetch live data for current calculations
    live_data = fetch_live_gameweek_data(gameweek)
    
    print(f"Player data saved to {player_data_file}")
    print(f"Data saved to {mini_league_file}")

    # Load the newly fetched data
    with open(mini_league_file, 'r') as file:
        mini_league_data = json.load(file)

    with open(player_data_file, 'r') as file:
        players_data = json.load(file)['elements']

    # Use REAL manager names everywhere instead of FPL team names. We keep the
    # original team name under 'team_name' and overwrite 'entry_name' so every
    # downstream function (fun facts, AI narrative, message, report) uses the
    # real name automatically.
    for _m in mini_league_data['standings']['results']:
        _m['team_name'] = _m['entry_name']
        _m['entry_name'] = _m.get('player_name') or _m['entry_name']

    player_id_to_name = {player['id']: player['web_name'] for player in players_data}
    # Update player points to use live data
    if live_data and 'elements' in live_data:
        player_id_to_points = {element['id']: element['stats']['total_points'] 
                              for element in live_data['elements']}
    else:
        # Fallback to bootstrap data
        player_id_to_points = {player['id']: player['event_points'] for player in players_data}
    player_id_to_position = {player['id']: player['element_type'] for player in players_data}

    output = f"Analysis generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    # Extract detailed gameweek data for all managers in the mini-league
    detail_by_entry = {}  # entry_id -> per-manager GW detail dict (for the infographic)
    for manager_data in mini_league_data['standings']['results']:
        # Use the real manager name, not the FPL team name.
        manager_name = manager_data.get('player_name') or manager_data['entry_name']
        gw_data = get_detailed_gw_data(manager_data, int(gameweek), player_id_to_name, player_id_to_points, player_id_to_position, mini_league_data)
        if gw_data:
            detail_by_entry[manager_data['entry']] = gw_data[0]

        output += f"\nManager: {manager_name}\n"
        output += "-" * 80 + "\n"
        for data in gw_data:
            output += f"Gameweek: {data['Gameweek']}\n"
            output += f"Points: {data['Points']}\n"
            output += f"Rank: {data['Rank']}\n"
            output += f"Captain: {data['Captain']}, {data['Captain Points']} points\n"
            output += f"Vice-Captain: {data['Vice-Captain']}, {data['Vice-Captain Points']} points\n"
            output += f"Transfers: {data['Transfers']}\n"
            output += f"Transfer Cost: {data['Transfer Cost']}\n"
            output += f"Team Value: {data['Team Value']}\n"
            output += f"Points on Bench: {data['Points on Bench']}\n"
            output += f"Bank Money: {data['Bank Money']}\n"
            output += f"Top Scorer: {data['Top Scorer']}, {data['Top Scorer Points']} points{' (on bench)' if not data['Top Scorer Played'] else ''}\n"
            output += f"Underperformer: {data['Underperformer']}, {data['Underperformer Points']} points\n"
            output += f"Formation: {data['Formation']}\n"
            output += f"Defensive Points: {data['Defensive Points']}\n"
            output += f"Attacking Points: {data['Attacking Points']}\n"
            output += f"Chip Used: {data['Chip Used']}\n"
            output += f"Performance vs Avg: {data['Performance vs Avg']}\n"
            output += f"Rank Movement: {data['Rank Movement']}\n"
            output += "-" * 80 + "\n"

    # Extract league standings
    league_standings = mini_league_data.get('standings', {}).get('results', [])
    # Use entry_history points (final score) instead of event_total (live calculated score)
    team_data = []
    for team in league_standings:
        gw_data = team.get('gameweek_data', {}).get(str(gameweek), {})
        entry_history = gw_data.get('entry_history', {})
        gross_points = entry_history.get('points', 0)  # API returns GROSS points
        transfer_cost = entry_history.get('event_transfers_cost', 0)
        net_points = gross_points - transfer_cost  # Calculate NET after hits
        team_data.append({
            'Team Name': team.get('player_name') or team['entry_name'],
            'Points': team['total'],
            'GW Points': net_points  # Use NET points
        })
    
    # Sort by GW points for current gameweek standings
    gw_standings = sorted(team_data, key=lambda x: x['GW Points'], reverse=True)
    
    # Calculate current_scores for AI insights and analysis (NET points after hits)
    current_scores = []
    for manager in mini_league_data['standings']['results']:
        gw_data = manager.get('gameweek_data', {}).get(str(gameweek), {})
        entry_history = gw_data.get('entry_history', {})
        gross_points = entry_history.get('points', 0)  # API returns GROSS points
        transfer_cost = entry_history.get('event_transfers_cost', 0)
        net_points = gross_points - transfer_cost  # NET after hit deduction
        current_scores.append({
            'manager': manager['entry_name'],
            'points': net_points,  # Keep 'points' as NET for compatibility
            'net_points': net_points,
            'gross_points': gross_points,
            'transfer_cost': transfer_cost,
            'took_hit': transfer_cost > 0
        })

    output += "\nLeague Standings:\n"
    output += "Team Name,Points\n"
    for team in team_data:
        output += f"{team['Team Name']},{team['Points']}\n"

    # Determine which players have finished / are playing / are yet to play so
    # live analysis is accurate (e.g. don't call a captain fail before kickoff).
    play_status = build_play_status_map(gameweek, players_data)

    # Calculate fun facts for the message
    fun_facts = calculate_weekly_fun_facts(mini_league_data, gameweek, player_id_to_name, player_id_to_points, play_status=play_status)

    # Get gameweek status (fixtures finished/remaining)
    gw_status = get_gameweek_status(gameweek)
    logger.info(f"GW{gameweek} status: {gw_status['fixtures_finished']}/{gw_status['total_fixtures']} fixtures complete, is_final={is_final}")
    print(f"GW{gameweek} status: {gw_status['fixtures_finished']}/{gw_status['total_fixtures']} fixtures, Final={is_final}")
    
    # Compute new analytics
    captaincy_regret_data = compute_captaincy_regret(
        mini_league_data, gameweek, player_id_to_points, player_id_to_name, play_status)
    luck_data = compute_luck_score(mini_league_data, gameweek, players_data, player_id_to_points)
    try:
        transfer_regret_data = compute_transfer_regret(mini_league_data, gameweek, player_id_to_name)
    except Exception as e:
        logger.warning(f"Transfer regret computation failed: {e}")
        transfer_regret_data = []
    archetypes = compute_manager_archetypes(mini_league_data, gameweek)

    # Build context strings for AI
    cap_regret_ctx = build_captaincy_regret_context(captaincy_regret_data)
    luck_ctx = build_luck_score_context(luck_data)
    transfer_regret_ctx = build_transfer_regret_context(transfer_regret_data)
    archetypes_ctx = build_archetypes_context(archetypes)
    points_left_ctx = build_points_left_on_table(mini_league_data, gameweek, captaincy_regret_data, luck_data)
    extra_context = "\n\n".join(filter(None, [cap_regret_ctx, luck_ctx, transfer_regret_ctx, archetypes_ctx, points_left_ctx]))

    # Generate AI insights using overall and historical data with player context
    print(f"Calling generate_ai_insights for GW{gameweek}...")
    print(f"Current scores count: {len(current_scores)}")
    ai_insights = generate_ai_insights(mini_league_data, gameweek, current_scores,
                                       player_id_to_name, player_id_to_points,
                                       is_final=is_final, gw_status=gw_status,
                                       play_status=play_status, players_data=players_data,
                                       extra_context=extra_context)
    logger.info(f"AI insights returned: {ai_insights is not None}, length: {len(ai_insights) if ai_insights else 0}")
    
    # -------------------------------------------------------------------- #
    # Single-image infographic report (replaces the old multi-PNG + PDF).
    # Build a rich data payload -> render modern HTML -> one tall high-DPI PNG.
    # -------------------------------------------------------------------- #
    import report as report_mod
    import report_template
    import importlib
    importlib.reload(report_mod)
    importlib.reload(report_template)

    gw_average = calculate_gw_average(mini_league_data, gameweek)
    league_name = mini_league_data.get('league', {}).get('name', 'Mini League')

    # -------------------------------------------------------------------- #
    # Image generation (DALL-E hero + manager photos)
    # -------------------------------------------------------------------- #
    # GW winner = top of current_scores (already sorted by net_points desc)
    gw_winner = current_scores[0] if current_scores else {}
    gw_winner_name = gw_winner.get("manager", "")
    gw_winner_pts = gw_winner.get("net_points", 0)

    hero_image_path = None
    manager_photos: Dict[str, str] = {}

    if is_final:
        try:
            hero_image_path = report_mod.generate_gw_hero_image(
                gw_winner_name, gw_winner_pts, gameweek, is_final=True)
        except Exception as e:
            logger.warning(f"Hero image generation failed: {e}")

        # Generate/fetch manager photos for all managers (one-time DALL-E cost, then cached)
        for m in mini_league_data['standings']['results']:
            mgr_name = m.get('player_name') or m['entry_name']
            archetype = archetypes.get(m['entry_name'], {}).get('label', '')
            try:
                photo_path = report_mod.get_or_generate_manager_photo(mgr_name, archetype)
                if photo_path:
                    manager_photos[mgr_name] = photo_path
            except Exception as e:
                logger.warning(f"Manager photo failed for {mgr_name}: {e}")
    else:
        # In live mode: only use cached photos (no DALL-E spend mid-GW)
        try:
            from fb_photo_scraper import load_photo_mapping
            manager_photos = load_photo_mapping()
        except Exception:
            pass
        # Check for cached avatars too
        for m in mini_league_data['standings']['results']:
            mgr_name = m.get('player_name') or m['entry_name']
            if mgr_name not in manager_photos:
                safe = "".join(c if c.isalnum() else "_" for c in mgr_name)
                cached = os.path.join(local_path, "photos", "avatars", f"{safe}.png")
                if os.path.exists(cached):
                    manager_photos[mgr_name] = cached

    payload = report_mod.build_payload(
        mini_league_data=mini_league_data,
        gameweek=gameweek,
        league_name=league_name,
        detail_by_entry=detail_by_entry,
        current_scores=current_scores,
        fun_facts=fun_facts,
        ai_insights=ai_insights,
        gw_average=gw_average,
        is_final=is_final,
        hero_image_path=hero_image_path,
        manager_photos=manager_photos,
        players_data=players_data,
    )

    payload_file = os.path.join(local_path, f"report_data_gw{gameweek}.json")
    report_mod.write_payload(payload, payload_file)
    print(f"Report payload saved to {payload_file}")

    html_str = report_template.render_report_html(payload)
    html_file = os.path.join(local_path, f"report_gw{gameweek}.html")
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_str)
    print(f"HTML report saved to {html_file}")

    png_file = os.path.join(local_path, f"report_gw{gameweek}.png")
    try:
        report_mod.render_html_to_png(html_file, png_file)
        print(f"Infographic image saved to {png_file}")
    except Exception as e:
        logger.error(f"Failed to render infographic PNG: {e}")
        print(f"WARNING: could not render PNG ({e}); HTML report is still available.")
    
    # Build a Messenger-friendly message with emojis, real line breaks, and
    # dividers between sections. Each block is appended only if it has content,
    # then the blocks are joined with a horizontal divider.
    DIVIDER = "━━━━━━━━━━━━━━━━━━━━"
    MEDALS = ["🥇", "🥈", "🥉"]
    sections: list[str] = []

    # Compute per-GW average for above/below indicator
    gw_avg_pts = (sum(t['GW Points'] for t in gw_standings) / len(gw_standings)
                  if gw_standings else 0)

    CHIP_EMOJI = {'3xc': '3️⃣', 'bboost': '🚀', 'freehit': '🆓', 'wildcard': '🃏'}

    # --- Header: full leaderboard (FINAL or LIVE) -------------------------
    if is_final:
        highest_score = gw_standings[0]['GW Points']
        winners = [t for t in gw_standings if t['GW Points'] == highest_score]

        if len(winners) == 1:
            header = f"🏆 GW{gameweek} CHAMPION\n{winners[0]['Team Name']} — {highest_score} pts"
        else:
            header = (f"🤝 GW{gameweek} TIED — {highest_score} pts each\n"
                      + "\n".join(t['Team Name'] for t in winners))

        # Full leaderboard for FINAL so everyone sees their exact place
        rows = []
        for i, team in enumerate(gw_standings):
            medal = MEDALS[i] if i < 3 else f"#{i+1}"
            delta = team['GW Points'] - gw_avg_pts
            delta_str = f" (+{delta:.0f})" if delta >= 0 else f" ({delta:.0f})"
            # Find overall season rank
            overall_r = next(
                (j + 1 for j, m in enumerate(
                    sorted(mini_league_data['standings']['results'],
                           key=lambda x: x.get('total', 0), reverse=True)
                ) if m['entry_name'] == team['Team Name']),
                "?"
            )
            m_data = next((m for m in mini_league_data['standings']['results']
                           if m['entry_name'] == team['Team Name']), {})
            chip = m_data.get('gameweek_data', {}).get(str(gameweek), {}).get('active_chip')
            chip_str = f" {CHIP_EMOJI.get(chip, '🎮')}" if chip else ""
            rows.append(f"{medal} {team['Team Name']}{chip_str} — {team['GW Points']}pts{delta_str} | Season #{overall_r}")

        sections.append(header + "\n\n" + "\n".join(rows))
    else:
        # Live standings — rich per-manager row with captain pts, players left, chips
        rows = []
        for i, team in enumerate(gw_standings):
            medal = MEDALS[i] if i < 3 else f"#{i+1}"
            delta = team['GW Points'] - gw_avg_pts
            delta_str = f" (+{delta:.0f})" if delta >= 0 else f" ({delta:.0f})"

            m_data = next((m for m in mini_league_data['standings']['results']
                           if m['entry_name'] == team['Team Name']), {})
            gw_pick_data = m_data.get('gameweek_data', {}).get(str(gameweek), {})
            picks = gw_pick_data.get('picks', [])
            starters = [p for p in picks if p.get('multiplier', 0) > 0]

            # Captain info
            cap = next((p for p in picks if p.get('is_captain')), None)
            if cap:
                cap_name = player_id_to_name.get(cap['element'], '?').split()[-1]
                cap_status = (play_status or {}).get(cap['element'], 'upcoming')
                cap_pts = player_id_to_points.get(cap['element'], 0) * cap.get('multiplier', 2)
                cap_icon = {'finished': '✓', 'playing': '⚡', 'upcoming': '⏳'}.get(cap_status, '?')
                if cap_status == 'finished':
                    cap_str = f" | C:{cap_name} {cap_pts}pts{cap_icon}"
                elif cap_status == 'playing':
                    cap_str = f" | C:{cap_name} {cap_pts}pts{cap_icon}"
                else:
                    cap_str = f" | C:{cap_name}{cap_icon}"
            else:
                cap_str = ""

            # Players yet to play / currently playing
            n_upcoming = sum(1 for p in starters if (play_status or {}).get(p['element']) == 'upcoming')
            n_live = sum(1 for p in starters if (play_status or {}).get(p['element']) == 'playing')
            if n_live > 0 and n_upcoming > 0:
                play_str = f" | {n_live}⚡ {n_upcoming}⏳left"
            elif n_live > 0:
                play_str = f" | {n_live}⚡ playing"
            elif n_upcoming > 0:
                play_str = f" | {n_upcoming}⏳ to play"
            else:
                play_str = ""

            chip = gw_pick_data.get('active_chip')
            chip_str = f" {CHIP_EMOJI.get(chip, '🎮')}" if chip else ""

            rows.append(
                f"{medal} {team['Team Name']}{chip_str} — {team['GW Points']}pts{delta_str}"
                f"{cap_str}{play_str}"
            )

        _fin = gw_status.get('fixtures_finished', 0)
        _live = gw_status.get('fixtures_in_progress', 0)
        _tot = gw_status.get('total_fixtures', 10)
        _rem = _tot - _fin - _live

        # Days elapsed since GW started / days until last game
        _now_utc = datetime.utcnow()
        _first_ko = gw_status.get('first_kickoff')  # datetime (UTC, naive)
        _last_ko  = gw_status.get('last_kickoff')
        _day_lines = []
        if _first_ko:
            _days_in = max(0, (_now_utc - _first_ko).days)
            _day_lines.append(f"Day {_days_in + 1} of GW{gameweek}")
        if _last_ko and _last_ko > _now_utc:
            _hrs_left = int((_last_ko - _now_utc).total_seconds() / 3600)
            if _hrs_left >= 24:
                _day_lines.append(f"{_hrs_left // 24}d {_hrs_left % 24}h until last game")
            else:
                _day_lines.append(f"{_hrs_left}h until last game")

        if _fin == 0 and _live == 0:
            _status_tag = f"0/{_tot} games played"
        elif _live > 0:
            _status_tag = f"{_fin}/{_tot} done · {_live} live · {_rem} left"
        else:
            _status_tag = f"{_fin}/{_tot} games done · {_rem} remaining"

        day_ctx = " · ".join(_day_lines)
        header = f"🏁 GW{gameweek}{' — ' + day_ctx if day_ctx else ''}\n{_status_tag}"
        sections.append(header + "\n" + "\n".join(rows))

    # --- Highlights (fun facts) — only show if player has actually played ---
    highlights: list[str] = []

    if fun_facts.get('comeback'):
        cf = fun_facts['comeback']
        n = cf['change']
        word = "place" if n == 1 else "places"
        highlights.append(f"📈 COMEBACK OF THE WEEK\n{cf['manager']} ⬆ {n} {word} in the table")

    if fun_facts.get('choke'):
        cf = fun_facts['choke']
        n = abs(cf['change'])
        word = "place" if n == 1 else "places"
        highlights.append(f"📉 CHOKE OF THE WEEK\n{cf['manager']} ⬇ {n} {word}")

    if fun_facts.get('captain_fail'):
        cf = fun_facts['captain_fail']
        highlights.append(
            f"🤡 CAPTAIN DISASTER\n"
            f"{cf['manager']} armband on {cf['captain']} — {cf['points']} pts. Painful."
        )

    if fun_facts.get('bench_hero'):
        cf = fun_facts['bench_hero']
        highlights.append(
            f"🪑 LEFT ON THE BENCH\n"
            f"{cf['manager']} watched {cf['player']} ({cf['points']} pts) warm the bench"
        )

    if fun_facts.get('differential_hero'):
        cf = fun_facts['differential_hero']
        highlights.append(
            f"💎 DIFFERENTIAL GENIUS\n"
            f"{cf['manager']} went rogue with {cf['player']} "
            f"({cf['points']} pts — only {cf['ownership_pct']:.0f}% of the league owns them)"
        )

    # Show who still has captain to play (only in live mode)
    if not is_final and play_status:
        pending_caps = []
        for m in mini_league_data['standings']['results']:
            picks = m.get('gameweek_data', {}).get(str(gameweek), {}).get('picks', [])
            cap = next((p for p in picks if p.get('is_captain')), None)
            if cap and play_status.get(cap['element']) == 'upcoming':
                cap_name = player_id_to_name.get(cap['element'], '?')
                pending_caps.append(f"{m['entry_name'].split()[0]} (C: {cap_name})")
        if pending_caps:
            highlights.append(f"⏳ CAPTAINS YET TO PLAY\n" + " | ".join(pending_caps[:6]))

    if highlights:
        sections.append("\n\n".join(highlights))

    # --- New analytics section ---
    analytics_lines = []
    if luck_data:
        luckiest = luck_data[0]
        unluckiest = luck_data[-1]
        if abs(luckiest['luck']) > 3 or abs(unluckiest['luck']) > 3:
            analytics_lines.append(
                f"🍀 LUCK THIS GW\n"
                f"Luckiest: {luckiest['manager']} (+{luckiest['luck']}pts over xPts)\n"
                f"Unluckiest: {unluckiest['manager']} ({unluckiest['luck']}pts below xPts)"
            )
    if captaincy_regret_data:
        worst_reg = next((r for r in captaincy_regret_data
                          if not r.get('pending') and not r.get('is_same') and r['regret'] > 0), None)
        nailed_it = next((r for r in reversed(captaincy_regret_data) if r.get('is_same')), None)
        if worst_reg:
            analytics_lines.append(
                f"🤦 CAPTAIN REGRET\n"
                f"{worst_reg['manager']} captained {worst_reg['actual_captain']} ({worst_reg['actual_pts']}pts) "
                f"while {worst_reg['best_captain']} sat in their squad ({worst_reg['best_pts']}pts). "
                f"That's {worst_reg['regret']}pts of pain."
            )
        if nailed_it:
            analytics_lines.append(
                f"✅ {nailed_it['manager']} nailed the captain pick — {nailed_it['actual_captain']} was the right call."
            )
    if transfer_regret_data:
        worst_transfer = next((r for r in transfer_regret_data
                               if r.get('worst') and r['worst']['regret'] > 5), None)
        if worst_transfer:
            w = worst_transfer['worst']
            analytics_lines.append(
                f"😬 TRANSFER REGRET\n"
                f"{worst_transfer['manager']} sold {w['out']} for {w['in']} in GW{w['gw']}. "
                f"{w['out']} then scored {w['out_pts']}pts vs {w['in']}'s {w['in_pts']}pts "
                f"over {w['window_gws']} GWs. Ouch."
            )
    pot_data = []
    for m_data in mini_league_data['standings']['results']:
        name = m_data['entry_name']
        gw_d = m_data.get('gameweek_data', {}).get(str(gameweek), {})
        eh = gw_d.get('entry_history', {})
        bench_pts = eh.get('points_on_bench', 0)
        transfer_cost = eh.get('event_transfers_cost', 0)
        cap_miss = max(0, next((r['regret'] for r in captaincy_regret_data if r['manager'] == name), 0))
        total_lost = bench_pts + cap_miss + transfer_cost
        if total_lost > 0:
            pot_data.append({'manager': name, 'total': total_lost,
                             'bench': bench_pts, 'cap': cap_miss, 'hit': transfer_cost})
    pot_data.sort(key=lambda x: x['total'], reverse=True)
    if pot_data and pot_data[0]['total'] >= 8:
        top = pot_data[0]
        analytics_lines.append(
            f"💸 POINTS LEFT ON TABLE\n"
            f"Biggest self-sabotage: {top['manager']} left {top['total']}pts on the table "
            f"({top['bench']}pts bench + {top['cap']}pts captain miss + {top['hit']}pts hit)"
        )
    if is_final and archetypes:
        archetype_lines = [f"{name}: {data['label']}" for name, data in archetypes.items()]
        analytics_lines.append("🎭 MANAGER ARCHETYPES\n" + "\n".join(archetype_lines))

    if analytics_lines:
        sections.append("\n\n".join(analytics_lines))

    # --- AI-generated recap ------------------------------------------------
    if ai_insights and len(str(ai_insights).strip()) > 0:
        sections.append(f"📰 MATCH REPORT\n\n{str(ai_insights).strip()}")
        logger.info(f"AI insights added to message: {len(str(ai_insights))} characters")
    else:
        logger.warning(
            f"AI insights not added to message - type: {type(ai_insights)}, "
            f"value: {repr(ai_insights)}"
        )

    message = ("\n\n" + DIVIDER + "\n\n").join(sections)

    # Strip markdown / collapse whitespace; emojis and non-BMP code points are
    # preserved (the FB sender now types via CDP Input.insertText).
    sanitized_message = sanitize_message_for_fb(message)
    
    # Write sanitized message to message.txt
    message_file = os.path.join(local_path, "message.txt")
    with open(message_file, 'w') as file:
        file.write(sanitized_message)
    
    logger.info(f"Message sanitized and saved to {message_file}")
    
    # Also add to main output
    output += f"\n{message}\n"

    # Save the output to a text file, overwriting any existing file
    output_file = f"league_analysis_gw{gameweek}.txt"
    output_file = os.path.join(local_path, output_file)
    with open(output_file, 'w') as file:
        file.write(output)

    print(output)
    print(f"Analysis saved to league_analysis_gw{gameweek}.txt")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, help="The current gameweek")
    parser.add_argument("--lid", type=int, help="The league id")
    parser.add_argument("--final", action="store_true", default=False, help="Whether this is the final analysis for the gameweek")
    args = parser.parse_args()
    return args

if __name__ == "__main__":
    args = parse_args()
    create_plots_directory(create_new=True)
    main(args)