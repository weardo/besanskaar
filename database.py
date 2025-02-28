import logging
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import os
import time


class Database:

    def __init__(self):
        uri = os.getenv("MONGO_URI")
        # self.client = MongoClient(os.getenv("MONGO_URI"),
        self.client = MongoClient(uri, tls=True)
        self.db = self.client['sanskaar']
        self.games = self.db['games']
        self.players = self.db['players']
        self.logs = self.db['game_logs']
        self.custom_cards = self.db['custom_cards']
        self.removed_cards = self.db['removed_cards']
        logging.getLogger("pymongo").setLevel(logging.WARNING)

    def get_custom_cards(self, card_type: str, only_approved=True):
        query = {"type": card_type}
        if only_approved:
            query["approved"] = True
        cards = self.custom_cards.find(query, {"_id": 0, "text": 1})
        return [card["text"] for card in cards]

    def add_custom_card(self, card_text: str, card_type: str,
                        added_by_id: int):
        card = {
            "text": card_text,
            "type": card_type,
            "added_by": added_by_id,
            "added_at": time.time(),
            "approved": False
        }
        self.custom_cards.insert_one(card)

    def approve_custom_card(self, card_text: str, moderator_id: int):
        self.custom_cards.update_one({
            "text": card_text,
            "approved": False
        }, {
            "$set": {
                "approved": True,
                "approved_by": moderator_id,
                "approved_at": time.time()
            }
        })

    def is_card_removed(self, card_text: str, card_type: str):
        return self.removed_cards.find_one({
            "text": card_text,
            "type": card_type
        }) is not None

    def log_game_start(self, channel_id, creator_id):
        self.games.insert_one({
            "channel_id": channel_id,
            "creator_id": creator_id,
            "start_time": time.time(),
            "status": "active",
            "players": []
        })
        self._add_log_entry("game_start", channel_id, creator_id)

    def log_player_join(self, channel_id, player_id):
        self.games.update_one({"channel_id": channel_id},
                              {"$push": {
                                  "players": player_id
                              }})
        self._add_log_entry("player_join", channel_id, player_id)

    def log_card_play(self, channel_id, player_id, card_text):
        self._add_log_entry("card_play", channel_id, player_id, card_text)

    def log_game_end(self, channel_id):
        self.games.update_one(
            {"channel_id": channel_id},
            {"$set": {
                "status": "completed",
                "end_time": time.time()
            }})
        self._add_log_entry("game_end", channel_id)

    def _add_log_entry(self,
                       log_type,
                       channel_id,
                       player_id=None,
                       card_text=None):
        log = {
            "type": log_type,
            "channel_id": channel_id,
            "timestamp": time.time()
        }
        if player_id:
            log["player_id"] = player_id
        if card_text:
            log["card_text"] = card_text

        self.logs.insert_one(log)
