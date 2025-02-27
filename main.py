"""
Required Bot Permissions:
- View Channels (for seeing text and voice channels)
- Send Messages (for responding to commands)
- Send Messages in Threads (for thread discussions)
- Read Message History (for tracking game progress)
- Connect (for voice channel verification)
- View Voice Channel Members (for player tracking)

Permission Integer: 103079488
Invite Link Format:
https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=103079488&scope=bot%20applications.commands
"""

import os
import discord
from discord.ext import commands
import logging
from game import GameManager
from database import Database

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize bot with required intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Privileged intent
intents.voice_states = True  # Privileged intent
bot = commands.Bot(command_prefix='!cah ', intents=intents)

# Initialize game manager and database
game_manager = GameManager()
db = Database()

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

@bot.command(name='start')
async def start_game(ctx):
    """Start a new game of Cards Against Humanity"""
    # Check if user is in a voice channel
    if not ctx.author.voice:
        await ctx.send("You need to be in a voice channel to start a game!")
        return

    if game_manager.is_game_active(ctx.channel.id):
        await ctx.send("A game is already in progress!")
        return

    game_manager.create_game(ctx.channel.id)
    await ctx.send("New game started! Players in the voice channel can join using `!cah join`")
    db.log_game_start(ctx.channel.id, ctx.author.id)

@bot.command(name='join')
async def join_game(ctx):
    """Join the current game"""
    # Check if user is in a voice channel
    if not ctx.author.voice:
        await ctx.send("You need to be in a voice channel to join the game!")
        return

    if not game_manager.is_game_active(ctx.channel.id):
        await ctx.send("No game is currently active. Start one with `!cah start`")
        return

    success = game_manager.add_player(ctx.channel.id, ctx.author.id, ctx.author.name)
    if success:
        await ctx.send(f"{ctx.author.name} has joined the game!")
        db.log_player_join(ctx.channel.id, ctx.author.id)
    else:
        await ctx.send("You're already in the game!")

@bot.command(name='draw')
async def draw_cards(ctx):
    """Draw your hand of white cards"""
    # Verify user is still in voice channel
    if not ctx.author.voice:
        await ctx.send("You need to stay in the voice channel to play!")
        return

    game = game_manager.get_game(ctx.channel.id)
    if not game:
        await ctx.send("No game is currently active!")
        return

    cards = game.draw_cards(ctx.author.id)
    if cards:
        # DM the cards to the player
        cards_text = "\n".join([f"{i+1}. {card}" for i, card in enumerate(cards)])
        await ctx.author.send(f"Your cards:\n{cards_text}")
        await ctx.send(f"Cards have been sent to {ctx.author.name} via DM!")
    else:
        await ctx.send("You're not in the game or already have cards!")

@bot.command(name='play')
async def play_card(ctx, card_number: int):
    """Play a card from your hand"""
    # Verify user is still in voice channel
    if not ctx.author.voice:
        await ctx.send("You need to stay in the voice channel to play!")
        return

    game = game_manager.get_game(ctx.channel.id)
    if not game:
        await ctx.send("No game is currently active!")
        return

    success = game.play_card(ctx.author.id, card_number - 1)
    if success:
        await ctx.send(f"{ctx.author.name} has played their card!")
        db.log_card_play(ctx.channel.id, ctx.author.id, card_number)
    else:
        await ctx.send("Invalid card number or it's not your turn!")

@bot.command(name='end')
async def end_game(ctx):
    """End the current game"""
    # Only allow game creator or admin to end game
    game = game_manager.get_game(ctx.channel.id)
    if not game:
        await ctx.send("No game is currently active!")
        return

    if game_manager.end_game(ctx.channel.id):
        await ctx.send("Game ended! Thanks for playing!")
        db.log_game_end(ctx.channel.id)
    else:
        await ctx.send("No game is currently active!")

@bot.command(name='rules')
async def show_rules(ctx):
    """Show game rules and commands"""
    rules_text = """
**Cards Against Humanity - Voice Chat Edition**
*A party game for horrible people, now in Discord!*

**How to Play:**
1. Join a voice channel
2. Use `!cah start` to start a new game
3. Others in the voice channel use `!cah join` to join
4. Use `!cah prompt` to draw a black card for the round
5. Players use `!cah draw` to get their white cards (sent via DM)
6. When it's your turn, use `!cah play <number>` to play a card

**Commands:**
`!cah start` - Start a new game (must be in voice channel)
`!cah join` - Join the current game (must be in voice channel)
`!cah prompt` - Draw a black card for the current round
`!cah draw` - Draw your hand of cards (sent via DM)
`!cah play <number>` - Play a card from your hand
`!cah end` - End the current game
`!cah rules` - Show this help message
    """
    await ctx.send(rules_text)

@bot.command(name='prompt')
async def draw_prompt(ctx):
    """Draw a black prompt card for the current round"""
    logger.debug(f"Prompt command requested by {ctx.author.name}")

    # Verify user is still in voice channel
    if not ctx.author.voice:
        logger.debug(f"User {ctx.author.name} not in voice channel")
        await ctx.send("You need to be in a voice channel to play!")
        return

    game = game_manager.get_game(ctx.channel.id)
    if not game:
        logger.debug(f"No active game in channel {ctx.channel.name}")
        await ctx.send("No game is currently active!")
        return

    black_card = game.start_round()
    if black_card:
        logger.info(f"Drew black card in channel {ctx.channel.name}: {black_card}")
        await ctx.send(f"📜 **Black Card**: {black_card}")
    else:
        logger.warning(f"No black cards available in channel {ctx.channel.name}")
        await ctx.send("No more black cards available!")


# Get Discord token and run bot
token = os.getenv('DISCORD_TOKEN')
if not token:
    logger.error("No Discord token found!")
    raise ValueError("Please set the DISCORD_TOKEN environment variable")

bot.run(token)