import random
import logging
from cards import create_card_manager
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

class Game:
    def __init__(self, allow_nsfw: bool = False):
        self.players = {}  # player_id: {name, cards, score}
        self.card_manager = create_card_manager(allow_nsfw)
        self.black_cards = self.card_manager.get_black_cards()
        self.white_cards = self.card_manager.get_white_cards()
        self.current_black_card = None
        self.played_cards = {}  # player_id: card
        self.round_in_progress = False
        self.current_prompt_drawer = None
        self.player_order = []
        self.allow_nsfw = allow_nsfw
        logger.debug(f"Game initialized with {len(self.black_cards)} black cards and {len(self.white_cards)} white cards")
        if allow_nsfw:
            logger.debug("NSFW content enabled")

    def add_player(self, player_id, player_name):
        if player_id not in self.players:
            self.players[player_id] = {
                'name': player_name,
                'cards': [],
                'score': 0
            }
            self.player_order.append(player_id)
            if len(self.player_order) == 1:  # First player becomes first prompt drawer
                self.current_prompt_drawer = player_id
            return True
        return False

    def draw_cards(self, player_id):
        if player_id not in self.players:
            return None

        player = self.players[player_id]
        while len(player['cards']) < 7:
            if not self.white_cards:
                return None  # No more cards to draw
            card = random.choice(self.white_cards)
            self.white_cards.remove(card)
            player['cards'].append(card['text'])

        return player['cards']

    def play_card(self, player_id, card_index):
        if player_id not in self.players:
            return False

        player = self.players[player_id]
        if card_index < 0 or card_index >= len(player['cards']):
            return False

        # Don't allow prompt drawer to play a card
        if player_id == self.current_prompt_drawer:
            return False

        card = player['cards'].pop(card_index)
        self.played_cards[player_id] = card

        # Check if all players (except prompt drawer) have played
        active_players = len(self.players) - 1  # Exclude prompt drawer
        if len(self.played_cards) == active_players:
            logger.info("All players have played their cards")
            return "all_played"

        return True

    def start_round(self):
        if not self.black_cards:
            logger.debug("No black cards remaining in deck")
            return None

        self.current_black_card = random.choice(self.black_cards)
        self.black_cards.remove(self.current_black_card)
        self.played_cards = {}
        self.round_in_progress = True

        logger.debug(f"Drew black card: {self.current_black_card['text']}")
        logger.debug(f"Remaining black cards: {len(self.black_cards)}")
        return self.current_black_card['text']

    def select_winner(self, winning_player_id):
        """Select the winning card and award points"""
        if not self.round_in_progress or winning_player_id not in self.played_cards:
            return False

        # Award point to winner
        self.players[winning_player_id]['score'] += 1
        logger.info(f"Player {self.players[winning_player_id]['name']} won the round! New score: {self.players[winning_player_id]['score']}")

        # Move to next prompt drawer
        self._cycle_prompt_drawer()
        self.round_in_progress = False
        return True

    def _cycle_prompt_drawer(self):
        """Cycle to the next player for drawing prompts"""
        if not self.player_order:
            return

        current_index = self.player_order.index(self.current_prompt_drawer)
        next_index = (current_index + 1) % len(self.player_order)
        self.current_prompt_drawer = self.player_order[next_index]
        logger.debug(f"New prompt drawer: {self.players[self.current_prompt_drawer]['name']}")

    def get_played_cards(self):
        """Get all played cards for selection"""
        return {player_id: {
            'card': card,
            'player_name': self.players[player_id]['name']
        } for player_id, card in self.played_cards.items()}

    def get_scores(self):
        """Get current scores for all players"""
        return {player_id: {
            'name': player['name'],
            'score': player['score']
        } for player_id, player in self.players.items()}

    def get_winner(self):
        """Get the player with the highest score"""
        if not self.players:
            return None

        # Handle tie by selecting the first player with highest score
        max_score = max(player['score'] for player in self.players.values())
        for player_id, player in self.players.items():
            if player['score'] == max_score:
                return {
                    'id': player_id,
                    'name': player['name'],
                    'score': max_score
                }
        return None

class GameManager:
    def __init__(self):
        self.games = {}  # channel_id: Game

    def create_game(self, channel_id, allow_nsfw: bool = False):
        """Create a new game with NSFW setting"""
        self.games[channel_id] = Game(allow_nsfw)

    def get_game(self, channel_id):
        return self.games.get(channel_id)

    def is_game_active(self, channel_id):
        return channel_id in self.games

    def end_game(self, channel_id):
        if channel_id in self.games:
            del self.games[channel_id]
            return True
        return False

    def add_player(self, channel_id, player_id, player_name):
        game = self.get_game(channel_id)
        if game:
            return game.add_player(player_id, player_name)
        return False