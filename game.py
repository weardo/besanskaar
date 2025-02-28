import random
import logging
from cards import create_card_manager
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

class Game:
    def __init__(self, allow_nsfw: bool = False, database=None):
        self.players = {}  # player_id: {id, name, cards, score}
        self.card_manager = create_card_manager(allow_nsfw, database)
        self.black_cards = self.card_manager.get_black_cards()
        self.white_cards = self.card_manager.get_white_cards()
        self.current_black_card = None
        self.played_cards = {}  # player_id: card
        self.round_in_progress = False
        self.current_prompt_drawer = None
        self.player_order = []
        self.allow_nsfw = allow_nsfw
        self.custom_answers = {}  # player_id: custom answer
        self.database = database  # Store database reference
        logger.debug(f"Game initialized with {len(self.black_cards)} black cards and {len(self.white_cards)} white cards")
        if allow_nsfw:
            logger.debug("NSFW content enabled")

    def add_custom_card(self, card_text: str, card_type: str, added_by_id: int) -> bool:
        """Add a custom card to the database"""
        if not self.card_manager:
            return False
        return self.card_manager.add_custom_card(card_text, card_type, added_by_id)

    def remove_card(self, card_text: str, card_type: str, removed_by_id: int) -> bool:
        """Remove a card from the game"""
        if not self.card_manager:
            return False
        return self.card_manager.remove_card(card_text, card_type, removed_by_id)

    def approve_custom_card(self, card_text: str, card_type: str, moderator_id: int) -> bool:
        """Approve a custom card"""
        if not self.card_manager:
            return False
        return self.card_manager.approve_custom_card(card_text, card_type, moderator_id)

    def play_custom_answer(self, player_id: int, custom_text: str) -> bool:
        """Submit a custom answer instead of playing a card"""
        if not self.round_in_progress or player_id not in self.players:
            return False

        # Don't allow prompt drawer to play
        if player_id == self.current_prompt_drawer:
            return False

        # Store the custom answer
        self.custom_answers[player_id] = custom_text
        self.played_cards[player_id] = custom_text

        # Check if all players (except prompt drawer) have played
        active_players = len(self.players) - 1  # Exclude prompt drawer
        if len(self.played_cards) == active_players:
            logger.info("All players have played their cards/answers")
            return "all_played"

        return True

    def set_player_dm_mode(self, player_id: int, enabled: bool) -> bool:
        """Enable or disable DM mode for a player"""
        if player_id in self.players:
            if self.players[player_id].get('dm_mode', True) == enabled: #Default to True
                return False
            self.players[player_id]['dm_mode'] = enabled
            logger.info(f"Player {self.players[player_id]['name']} {'enabled' if enabled else 'disabled'} DM mode")
            return True
        return False

    def remove_player(self, player_id: int) -> bool:
        """Remove a player from the game"""
        if player_id not in self.players:
            return False

        # Remove player's played card if any
        self.played_cards.pop(player_id, None)

        # Remove from player order
        if player_id in self.player_order:
            self.player_order.remove(player_id)

        # If this was the prompt drawer, move to next player
        if player_id == self.current_prompt_drawer:
            self._cycle_prompt_drawer()

        # Remove player
        player_name = self.players[player_id]['name']
        del self.players[player_id]

        logger.info(f"Player {player_name} removed from game")
        return True

    def _cycle_prompt_drawer(self):
        """Cycle to the next player for drawing prompts"""
        if not self.player_order:
            self.current_prompt_drawer = None
            return

        if self.current_prompt_drawer in self.player_order:
            current_index = self.player_order.index(self.current_prompt_drawer)
            next_index = (current_index + 1) % len(self.player_order)
        else:
            next_index = 0

        self.current_prompt_drawer = self.player_order[next_index]
        logger.debug(f"New prompt drawer: {self.players[self.current_prompt_drawer]['name']}")

    def update_nsfw_setting(self, allow_nsfw: bool) -> bool:
        """Update NSFW setting and refresh all cards"""
        try:
            if self.allow_nsfw == allow_nsfw:
                logger.debug(f"NSFW setting already set to {allow_nsfw}")
                return False

            # Update card manager
            if self.card_manager.update_nsfw_setting(allow_nsfw):
                self.allow_nsfw = allow_nsfw
                logger.debug(f"Updating NSFW setting to {allow_nsfw}")

                # Get new card decks
                try:
                    self.black_cards = self.card_manager.get_black_cards()
                    self.white_cards = self.card_manager.get_white_cards()
                    logger.debug(f"Loaded {len(self.black_cards)} black cards and {len(self.white_cards)} white cards")
                except Exception as e:
                    logger.error(f"Failed to load new card decks: {str(e)}")
                    return False

                # Filter current black card if it exists
                if self.current_black_card:
                    try:
                        valid_texts = {card['text'] for card in self.black_cards}
                        if self.current_black_card['text'] not in valid_texts:
                            logger.info("Current black card was filtered due to NSFW setting change")
                            self.current_black_card = None
                            self.round_in_progress = False
                    except Exception as e:
                        logger.error(f"Error filtering black card: {str(e)}")
                        self.current_black_card = None
                        self.round_in_progress = False

                # Filter each player's hand
                for player_id, player in self.players.items():
                    try:
                        old_card_count = len(player['cards'])
                        filtered_cards = self.card_manager.filter_cards(player['cards'])
                        player['cards'] = filtered_cards
                        # Draw new cards to replace filtered ones
                        self.draw_cards(player['id'])
                        logger.info(f"Player {player['name']}: {old_card_count - len(filtered_cards)} cards filtered, drew new cards")
                    except Exception as e:
                        logger.error(f"Error updating cards for player {player['name']}: {str(e)}")
                        player['cards'] = []  # Reset hand on error
                        self.draw_cards(player['id'])  # Try to draw new cards

                # Filter played cards
                try:
                    old_played_count = len(self.played_cards)
                    valid_cards = set(self.card_manager.filter_cards([card for card in self.played_cards.values()]))
                    self.played_cards = {pid: card for pid, card in self.played_cards.items()
                                        if card in valid_cards}
                    logger.info(f"Played cards: {old_played_count - len(self.played_cards)} cards filtered")
                except Exception as e:
                    logger.error(f"Error filtering played cards: {str(e)}")
                    self.played_cards = {}  # Reset played cards on error

                logger.info(f"Updated NSFW setting to {allow_nsfw}")
                return True
            return False
        except Exception as e:
            logger.error(f"Critical error updating NSFW setting: {str(e)}")
            return False

    def add_player(self, player_id, player_name):
        if player_id not in self.players:
            self.players[player_id] = {
                'id': player_id,  # Store ID for reference
                'name': player_name,
                'cards': [],
                'score': 0,
                'dm_mode': True  # DM mode is now always enabled
            }
            self.player_order.append(player_id)
            if len(self.player_order) == 1:  # First player becomes first prompt drawer
                self.current_prompt_drawer = player_id
            return True
        return False

    def draw_cards(self, player_id):
        """Draw cards until player has 7 cards"""
        if player_id not in self.players:
            logger.warning(f"Attempted to draw cards for non-existent player {player_id}")
            return None

        player = self.players[player_id]
        cards_needed = 7 - len(player['cards'])
        if cards_needed <= 0:
            logger.debug(f"Player {player['name']} already has a full hand")
            return player['cards']

        cards_drawn = 0
        while len(player['cards']) < 7:
            if not self.white_cards:
                logger.warning("No more white cards available in deck")
                break
            try:
                card = random.choice(self.white_cards)
                self.white_cards.remove(card)
                player['cards'].append(card['text'])
                cards_drawn += 1
            except Exception as e:
                logger.error(f"Error drawing card: {str(e)}")
                break

        logger.info(f"Drew {cards_drawn} cards for player {player['name']}")
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
        self.custom_answers = {} #clear custom answers for new round
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

        # Top up all players' cards
        for player_id in self.players:
            if player_id != self.current_prompt_drawer:  # Skip prompt drawer
                self.draw_cards(player_id)

        # Move to next prompt drawer
        self._cycle_prompt_drawer()
        self.round_in_progress = False
        return True

    def get_played_cards(self, include_players: bool = False):
        """Get all played cards for selection"""
        if include_players:
            return {player_id: {
                'card': card,
                'player_name': self.players[player_id]['name']
            } for player_id, card in self.played_cards.items()}
        else:
            # Return only cards without player names for suspense
            return list(self.played_cards.values())

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
    def __init__(self, database=None):
        self.games = {}  # channel_id: Game
        self.database = database

    def create_game(self, channel_id, allow_nsfw: bool = False):
        """Create a new game with NSFW setting"""
        self.games[channel_id] = Game(allow_nsfw, self.database)

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