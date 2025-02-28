import json
import os
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class CardManager:
    def __init__(self, allow_nsfw: bool = False):
        self.allow_nsfw = allow_nsfw
        self.cards_dir = "data/cards"
        self.black_cards = []
        self.white_cards = []
        self._load_cards()

    def _load_cards(self):
        """Load and filter cards based on NSFW setting"""
        # Load SFW cards
        self._load_card_set("sfw_black_cards.json", self.black_cards)
        self._load_card_set("sfw_white_cards.json", self.white_cards)

        # Load NSFW cards if enabled
        if self.allow_nsfw:
            self._load_card_set("nsfw_black_cards.json", self.black_cards)
            self._load_card_set("nsfw_white_cards.json", self.white_cards)

        logger.info(f"Loaded {len(self.black_cards)} black cards and {len(self.white_cards)} white cards")
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
        return self.black_cards

    def get_white_cards(self) -> List[Dict[str, Any]]:
        """Get all available white cards"""
        return self.white_cards

def create_card_manager(allow_nsfw: bool = False) -> CardManager:
    """Factory function to create a CardManager instance"""
    return CardManager(allow_nsfw)