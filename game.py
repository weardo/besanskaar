import random
from cards import load_black_cards, load_white_cards

class Game:
    def __init__(self):
        self.players = {}  # player_id: {name, cards, score}
        self.black_cards = load_black_cards()
        self.white_cards = load_white_cards()
        self.current_black_card = None
        self.played_cards = {}  # player_id: card
        self.round_in_progress = False
        
    def add_player(self, player_id, player_name):
        if player_id not in self.players:
            self.players[player_id] = {
                'name': player_name,
                'cards': [],
                'score': 0
            }
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
            player['cards'].append(card)
        
        return player['cards']
    
    def play_card(self, player_id, card_index):
        if player_id not in self.players:
            return False
        
        player = self.players[player_id]
        if card_index < 0 or card_index >= len(player['cards']):
            return False
        
        card = player['cards'].pop(card_index)
        self.played_cards[player_id] = card
        return True
    
    def start_round(self):
        if not self.black_cards:
            return None
        
        self.current_black_card = random.choice(self.black_cards)
        self.black_cards.remove(self.current_black_card)
        self.played_cards = {}
        self.round_in_progress = True
        return self.current_black_card

class GameManager:
    def __init__(self):
        self.games = {}  # channel_id: Game
        
    def create_game(self, channel_id):
        self.games[channel_id] = Game()
        
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
