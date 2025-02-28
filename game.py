"""Game management for Cards Against Humanity"""
import random
import logging
from cards import load_black_cards, load_white_cards
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# Create singleton instance
_instance = None

class GameManager:
    def __init__(self):
        self.games: Dict[int, Game] = {}  # channel_id: Game
        logger.info("GameManager initialized")

    @classmethod
    def get_instance(cls):
        global _instance
        if _instance is None:
            _instance = cls()
        return _instance

    def create_game(self, channel_id: int):
        """Create a new game in a channel"""
        self.games[channel_id] = Game(channel_id)
        logger.debug(f"Created new game in channel {channel_id}. Active games: {list(self.games.keys())}")
        logger.info(f"Created new game in channel {channel_id}")

    def get_game(self, channel_id: int) -> Optional['Game']:
        """Get a game by channel ID"""
        game = self.games.get(channel_id)
        logger.debug(f"Getting game for channel {channel_id}. Found: {game is not None}")
        return game

    def is_game_active(self, channel_id: int) -> bool:
        """Check if a game is active in a channel"""
        is_active = channel_id in self.games
        logger.debug(f"Checking if game is active in channel {channel_id}: {is_active}")
        return is_active

    async def add_player(self, channel_id: int, player_id: int, player_name: str, dm_channel) -> bool:
        """Add a player to a game"""
        game = self.get_game(channel_id)
        if game:
            return await game.add_player(player_id, player_name, dm_channel)
        return False

    def end_game(self, channel_id: int) -> bool:
        """End a game in a channel"""
        if channel_id in self.games:
            del self.games[channel_id]
            logger.info(f"Ended game in channel {channel_id}")
            return True
        return False

class Game:
    def __init__(self, channel_id: int):
        self.channel_id = channel_id
        self.players: Dict[int, Dict] = {}  # player_id: {name, cards, score, dm_channel}
        self.black_cards = load_black_cards()
        self.white_cards = load_white_cards()
        self.current_black_card = None
        self.played_cards = {}  # player_id: card
        self.round_in_progress = False
        self.current_prompt_drawer = None  # Track who's drawing the prompt
        self.player_order = []  # List to track player order for turns
        logger.debug(f"Game initialized with {len(self.black_cards)} black cards and {len(self.white_cards)} white cards")

    async def add_player(self, player_id: int, player_name: str, dm_channel) -> bool:
        """Add a player to the game with their DM channel"""
        if player_id not in self.players:
            self.players[player_id] = {
                'name': player_name,
                'cards': [],
                'score': 0,
                'dm_channel': dm_channel
            }
            self.player_order.append(player_id)
            if len(self.player_order) == 1:  # First player becomes first prompt drawer
                self.current_prompt_drawer = player_id
            logger.info(f"Player {player_name} joined the game")
            return True
        return False

    def draw_cards(self, player_id: int) -> Optional[List[str]]:
        """Draw cards for a player"""
        if player_id not in self.players:
            return None

        player = self.players[player_id]
        while len(player['cards']) < 7:
            if not self.white_cards:
                return None  # No more cards to draw
            card = random.choice(self.white_cards)
            self.white_cards.remove(card)
            player['cards'].append(card)

        logger.debug(f"Player {player['name']} drew cards: {player['cards']}")
        return player['cards']

    def play_card(self, player_id: int, card_index: int) -> bool:
        """Play a card from a player's hand"""
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
        logger.info(f"Player {player['name']} played card: {card}")
        return True

    async def handle_played_card(self, player_id: int, card_index: int) -> bool:
        """Handle a played card and check if all players have played"""
        success = self.play_card(player_id, card_index)
        if success:
            # Check if all players except prompt drawer have played
            active_players = len(self.players) - 1  # Excluding prompt drawer
            cards_played = len(self.played_cards)

            if cards_played == active_players:
                # All players have played, send winner selection to prompt drawer
                prompt_drawer = self.players[self.current_prompt_drawer]
                dm_channel = prompt_drawer['dm_channel']
                if dm_channel:
                    from ui_components import send_winner_selection_dm
                    await send_winner_selection_dm(dm_channel, self.channel_id, self.get_played_cards())

        return success


    def start_round(self) -> Optional[str]:
        """Start a new round by drawing a black card"""
        if not self.black_cards:
            logger.debug("No black cards remaining in deck")
            return None

        self.current_black_card = random.choice(self.black_cards)
        self.black_cards.remove(self.current_black_card)
        self.played_cards = {}
        self.round_in_progress = True

        logger.debug(f"Drew black card: {self.current_black_card}")
        logger.debug(f"Remaining black cards: {len(self.black_cards)}")
        return self.current_black_card

    def select_winner(self, winning_player_id: int) -> bool:
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

    def get_played_cards(self) -> Dict[int, Dict[str, str]]:
        """Get all played cards for selection"""
        return {player_id: {
            'card': card,
            'player_name': self.players[player_id]['name']
        } for player_id, card in self.played_cards.items()}

    def get_scores(self) -> Dict[int, Dict[str, any]]:
        """Get current scores for all players"""
        return {player_id: {
            'name': player['name'],
            'score': player['score']
        } for player_id, player in self.players.items()}

    def get_winner(self) -> Optional[Dict[str, any]]:
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

    def get_player_dm_channel(self, player_id: int):
        """Get a player's DM channel"""
        return self.players.get(player_id, {}).get('dm_channel')

    def remove_player(self, player_id: int) -> bool:
        """Remove a player from the game"""
        if player_id in self.players:
            player_name = self.players[player_id]['name']
            del self.players[player_id]
            if player_id in self.player_order:
                self.player_order.remove(player_id)
            if player_id == self.current_prompt_drawer:
                self._cycle_prompt_drawer()
            logger.info(f"Player {player_name} left the game")
            return True
        return False