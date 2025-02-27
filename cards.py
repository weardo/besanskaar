import json
import os

def load_black_cards():
    with open('data/black_cards.json', 'r') as f:
        return json.load(f)

def load_white_cards():
    with open('data/white_cards.json', 'r') as f:
        return json.load(f)
