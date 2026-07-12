import asyncio
from datetime import datetime, timezone
from db import sessions, games, challenge_scores

async def run_analysis():
    print("🔍 Connecting to MongoDB and fetching analytics...")
    
    # ── FOCUS SESSIONS ──
    total_sessions = await sessions.count_documents({})
    ended_sessions = await sessions.count_documents({"phase": "ended"})
    active_sessions = await sessions.count_documents({"phase": "active"})
    
    # Fetch all sessions for aggregate stats
    all_sessions = []
    async for s in sessions.find({}):
        all_sessions.append(s)
        
    unique_focusers = set()
    total_focus_minutes = 0
    tree_counts = {}
    duration_counts = {}
    
    for s in all_sessions:
        # Sum duration if session ended
        if s.get("phase") == "ended":
            duration = s.get("duration", 0)
            parts = s.get("participants", {})
            total_focus_minutes += duration * len(parts)
            
            tree = s.get("tree", "unknown").lower()
            tree_counts[tree] = tree_counts.get(tree, 0) + 1
            
            duration_counts[duration] = duration_counts.get(duration, 0) + 1
            
        for user_id in s.get("participants", {}):
            unique_focusers.add(user_id)
            
    # Sort popular trees and durations
    sorted_trees = sorted(tree_counts.items(), key=lambda x: x[1], reverse=True)
    sorted_durations = sorted(duration_counts.items(), key=lambda x: x[1], reverse=True)

    # ── GAMES ──
    total_games = await games.count_documents({})
    ttt_count = await games.count_documents({"game_type": "tictactoe"})
    c4_count = await games.count_documents({"game_type": "connect4"})
    
    pvc_count = await games.count_documents({"vs_computer": True})
    pvp_count = await games.count_documents({"vs_computer": False})
    
    # Difficulty breakdown
    pvc_easy = await games.count_documents({"vs_computer": True, "difficulty": "easy"})
    pvc_medium = await games.count_documents({"vs_computer": True, "difficulty": "medium"})
    pvc_evil = await games.count_documents({"vs_computer": True, "difficulty": "evil"})
    
    # Unique players
    unique_players = set()
    async for g in games.find({}):
        p1 = g.get("player1_id")
        p2 = g.get("player2_id")
        if p1: unique_players.add(p1)
        if p2 and p2 != 0: unique_players.add(p2) # 0 is Toothless

    # ── CHALLENGE SCORES ──
    total_scores_logged = await challenge_scores.count_documents({})
    unique_challengers = set()
    total_points = 0
    
    async for sc in challenge_scores.find({}):
        unique_challengers.add(sc.get("user_id"))
        try:
            total_points += int(sc.get("points", 0))
        except (ValueError, TypeError):
            pass

    # ── PRINT REPORT ──
    print("\n" + "═"*50)
    print("📊 STARBURST BOT USAGE & ANALYTICS REPORT")
    print("═"*50)
    
    print("\n🌱 FOCUS SESSIONS (Forest Integration)")
    print("─"*40)
    print(f"• Total Focus Sessions Created : {total_sessions}")
    print(f"• Active Sessions Currently    : {active_sessions}")
    print(f"• Ended Sessions (Completed)   : {ended_sessions}")
    print(f"• Unique Focus Participants    : {len(unique_focusers)}")
    print(f"• Total Focus Time Completed   : {total_focus_minutes / 60:.1f} hours ({total_focus_minutes} minutes)")
    
    if sorted_trees:
        print("\n📈 Most Popular Trees:")
        for tree, count in sorted_trees[:5]:
            print(f"  - {tree.title()}: {count} times")
            
    if sorted_durations:
        print("\n⏳ Most Common Session Lengths:")
        for dur, count in sorted_durations[:5]:
            print(f"  - {dur} minutes: {count} times")

    print("\n🎮 COMPLETED GAMES STATS")
    print("─"*40)
    print(f"• Total Completed Games        : {total_games}")
    print(f"  ├─ Tic Tac Toe               : {ttt_count}")
    print(f"  └─ Connect 4                 : {c4_count}")
    print(f"• Matchmaking Type:")
    print(f"  ├─ vs. Toothless (Computer)  : {pvc_count}")
    print(f"  │  ├─ Easy                   : {pvc_easy}")
    print(f"  │  ├─ Medium                 : {pvc_medium}")
    print(f"  │  └─ Evil                   : {pvc_evil}")
    print(f"  └─ vs. Players (PvP 1v1)     : {pvp_count}")
    print(f"• Unique Players Active        : {len(unique_players)}")

    print("\n🌿 21-DAY STUDY CHALLENGE")
    print("─"*40)
    print(f"• Total Check-ins Logged       : {total_scores_logged}")
    print(f"• Unique Active Challengers    : {len(unique_challengers)}")
    print(f"• Total Score Points Awarded   : {total_points} pts")
    print("═"*50 + "\n")

if __name__ == "__main__":
    asyncio.run(run_analysis())
