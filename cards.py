import json
import os
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class CardManager:

    def __init__(self, allow_nsfw: bool = False, database=None):
        self.allow_nsfw = allow_nsfw
        self.cards_dir = "data/cards"
        self.black_cards = []
        self.white_cards = []
        self.database = database
        self._load_cards()

    def _load_cards(self):
        """Load and filter cards based on NSFW setting"""
        self.black_cards = []  # Clear existing cards
        self.white_cards = []  # Clear existing cards

        # Load SFW cards
        self._load_card_set("sfw_black_cards.json", self.black_cards)
        self._load_card_set("sfw_white_cards.json", self.white_cards)

        # Load NSFW cards if enabled
        if self.allow_nsfw:
            self._load_card_set("nsfw_black_cards.json", self.black_cards)
            self._load_card_set("nsfw_white_cards.json", self.white_cards)

        # Load approved custom cards if database is available
        if self.database:
            custom_black = self.database.get_custom_cards('black',
                                                          only_approved=True)
            custom_white = self.database.get_custom_cards('white',
                                                          only_approved=True)

            # Add custom cards to the deck
            self.black_cards.extend([{
                'text': text,
                'nsfw': False,
                'pick': 1
            } for text in custom_black])
            self.white_cards.extend([{
                'text': text,
                'nsfw': False
            } for text in custom_white])

        # Remove any cards that have been marked as removed
        # if self.database:
        #     self.black_cards = [card for card in self.black_cards
        #                       if not self.database.is_card_removed(card['text'], 'black')]
        #     self.white_cards = [card for card in self.white_cards
        #                       if not self.database.is_card_removed(card['text'], 'white')]

        logger.info(
            f"Loaded {len(self.black_cards)} black cards and {len(self.white_cards)} white cards"
        )
        if self.allow_nsfw:
            logger.info("NSFW content is enabled")
        else:
            logger.info("NSFW content is disabled")

    def _load_card_set(self, filename: str, card_list: List[Dict[str, Any]]):
        """Load cards from a JSON file if it exists"""
        file_path = os.path.join(self.cards_dir, filename)
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    card_list.extend(data['cards'])
        except Exception as e:
            logger.error(f"Error loading cards from {filename}: {str(e)}")

    def get_black_cards(self) -> List[Dict[str, Any]]:
        """Get all available black cards"""
        return self.black_cards.copy()

    def get_white_cards(self) -> List[Dict[str, Any]]:
        """Get all available white cards"""
        return self.white_cards.copy()

    def update_nsfw_setting(self, allow_nsfw: bool) -> bool:
        """Update NSFW setting and reload cards"""
        if self.allow_nsfw == allow_nsfw:
            return False

        self.allow_nsfw = allow_nsfw
        self._load_cards()
        return True

    def filter_cards(self, cards: List[str]) -> List[str]:
        """Filter a list of cards based on current NSFW setting"""
        # Get all current valid card texts
        valid_texts = {card['text'] for card in self.white_cards}
        # Filter and return only cards that exist in current deck
        return [card for card in cards if card in valid_texts]

    def add_custom_card(self, card_text: str, card_type: str,
                        added_by_id: int) -> bool:
        """Add a custom card to the database"""
        if not self.database:
            return False

        success = self.database.add_custom_card(card_text, card_type,
                                                added_by_id)
        if success:
            logger.info(f"Added new custom {card_type} card: {card_text}")
        return success

    def remove_card(self, card_text: str, card_type: str,
                    removed_by_id: int) -> bool:
        """Remove a card from the game"""
        if not self.database:
            return False

        success = self.database.remove_card(card_text, card_type,
                                            removed_by_id)
        if success:
            logger.info(f"Removed {card_type} card: {card_text}")
            self._load_cards()  # Reload cards to apply removal
        return success

    def approve_custom_card(self, card_text: str, card_type: str,
                            moderator_id: int) -> bool:
        """Approve a custom card"""
        if not self.database:
            return False

        success = self.database.approve_custom_card(card_text, card_type,
                                                    moderator_id)
        if success:
            logger.info(f"Approved custom {card_type} card: {card_text}")
            self._load_cards()  # Reload cards to include newly approved card
        return success


def create_card_manager(allow_nsfw: bool = False,
                        database=None) -> CardManager:
    """Factory function to create a CardManager instance"""
    return CardManager(allow_nsfw, database)
