from replit import db
import time
import json

class Database:
    def __init__(self):
        # Initialize database structure if it doesn't exist
        if 'games' not in db:
            db['games'] = json.dumps({})
        if 'players' not in db:
            db['players'] = json.dumps({})
        if 'game_logs' not in db:
            db['game_logs'] = json.dumps([])

    def log_game_start(self, channel_id, creator_id):
        games = json.loads(db['games'])
        games[str(channel_id)] = {
            'start_time': time.time(),
            'creator_id': creator_id,
            'players': [],
            'status': 'active'
        }
        db['games'] = json.dumps(games)
        
        self._add_log_entry({
            'type': 'game_start',
            'channel_id': channel_id,
            'creator_id': creator_id,
            'timestamp': time.time()
        })

    def log_player_join(self, channel_id, player_id):
        games = json.loads(db['games'])
        if str(channel_id) in games:
            games[str(channel_id)]['players'].append(player_id)
            db['games'] = json.dumps(games)
        
        self._add_log_entry({
            'type': 'player_join',
            'channel_id': channel_id,
            'player_id': player_id,
            'timestamp': time.time()
        })

    def log_card_play(self, channel_id, player_id, card_number):
        self._add_log_entry({
            'type': 'card_play',
            'channel_id': channel_id,
            'player_id': player_id,
            'card_number': card_number,
            'timestamp': time.time()
        })

    def log_game_end(self, channel_id):
        games = json.loads(db['games'])
        if str(channel_id) in games:
            games[str(channel_id)]['status'] = 'completed'
            games[str(channel_id)]['end_time'] = time.time()
            db['games'] = json.dumps(games)
        
        self._add_log_entry({
            'type': 'game_end',
            'channel_id': channel_id,
            'timestamp': time.time()
        })

    def _add_log_entry(self, entry):
        logs = json.loads(db['game_logs'])
        logs.append(entry)
        db['game_logs'] = json.dumps(logs)
