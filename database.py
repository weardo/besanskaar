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
        if 'custom_cards' not in db:
            db['custom_cards'] = json.dumps({
                'white': [],  # {text, added_by, added_at, approved}
                'black': []   # {text, added_by, added_at, approved}
            })
        if 'removed_cards' not in db:
            db['removed_cards'] = json.dumps({
                'white': [],  # {text, removed_by, removed_at}
                'black': []   # {text, removed_by, removed_at}
            })

    def add_custom_card(self, card_text: str, card_type: str, added_by_id: int) -> bool:
        """Add a custom card to the database"""
        try:
            custom_cards = json.loads(db['custom_cards'])

            # Don't add if card already exists
            if any(card['text'] == card_text for card in custom_cards[card_type]):
                return False

            custom_cards[card_type].append({
                'text': card_text,
                'added_by': added_by_id,
                'added_at': time.time(),
                'approved': False  # Cards need moderator approval by default
            })

            db['custom_cards'] = json.dumps(custom_cards)
            return True
        except Exception as e:
            print(f"Error adding custom card: {str(e)}")
            return False

    def remove_card(self, card_text: str, card_type: str, removed_by_id: int) -> bool:
        """Remove a card from the game"""
        try:
            removed_cards = json.loads(db['removed_cards'])

            # Don't add if already removed
            if any(card['text'] == card_text for card in removed_cards[card_type]):
                return False

            removed_cards[card_type].append({
                'text': card_text,
                'removed_by': removed_by_id,
                'removed_at': time.time()
            })

            db['removed_cards'] = json.dumps(removed_cards)
            return True
        except Exception as e:
            print(f"Error removing card: {str(e)}")
            return False

    def approve_custom_card(self, card_text: str, card_type: str, moderator_id: int) -> bool:
        """Approve a custom card for use in games"""
        try:
            custom_cards = json.loads(db['custom_cards'])

            # Find and approve the card
            for card in custom_cards[card_type]:
                if card['text'] == card_text and not card['approved']:
                    card['approved'] = True
                    card['approved_by'] = moderator_id
                    card['approved_at'] = time.time()
                    db['custom_cards'] = json.dumps(custom_cards)
                    return True

            return False
        except Exception as e:
            print(f"Error approving custom card: {str(e)}")
            return False

    def get_custom_cards(self, card_type: str, only_approved: bool = True) -> list:
        """Get list of custom cards"""
        try:
            custom_cards = json.loads(db['custom_cards'])
            if only_approved:
                return [card['text'] for card in custom_cards[card_type] if card['approved']]
            return [card['text'] for card in custom_cards[card_type]]
        except Exception as e:
            print(f"Error getting custom cards: {str(e)}")
            return []

    def is_card_removed(self, card_text: str, card_type: str) -> bool:
        """Check if a card has been removed from the game"""
        try:
            removed_cards = json.loads(db['removed_cards'])
            return any(card['text'] == card_text for card in removed_cards[card_type])
        except Exception as e:
            print(f"Error checking removed card: {str(e)}")
            return False

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