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

# Initialize bot with required intents and command prefix
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Privileged intent
intents.voice_states = True  # Privileged intent
bot = commands.Bot(command_prefix=['.cah ', '!cah '], intents=intents)

# Initialize game manager and database
game_manager = GameManager()
db = Database()

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    try:
        # Sync commands in background to avoid blocking
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

    # Log startup status
    logger.info("Bot is ready to play Cards Against Humanity!")
    logger.info("Use '.cah s' to start a new game or '.cah r' to see all commands")

@bot.command(name='s', help='Start a new game')
async def start_game(ctx):
    """Start a new game of Cards Against Humanity"""
    if not ctx.author.voice:
        await ctx.send("You need to be in a voice channel to start a game!")
        return

    if game_manager.is_game_active(ctx.channel.id):
        await ctx.send("A game is already in progress!")
        return

    game_manager.create_game(ctx.channel.id)
    await ctx.send("New game started! Players in the voice channel can join using `.cah j`")
    db.log_game_start(ctx.channel.id, ctx.author.id)

@bot.command(name='j', help='Join the current game')
async def join_game(ctx):
    """Join the current game"""
    if not ctx.author.voice:
        await ctx.send("You need to be in a voice channel to join the game!")
        return

    if not game_manager.is_game_active(ctx.channel.id):
        await ctx.send("No game is currently active. Start one with `.cah s`")
        return

    success = game_manager.add_player(ctx.channel.id, ctx.author.id, ctx.author.name)
    if success:
        await ctx.send(f"{ctx.author.name} has joined the game!")
        db.log_player_join(ctx.channel.id, ctx.author.id)
    else:
        await ctx.send("You're already in the game!")

@bot.command(name='d', help='Draw white cards')
async def draw_cards(ctx):
    """Draw your hand of white cards"""
    if not ctx.author.voice:
        await ctx.send("You need to stay in the voice channel to play!")
        return

    game = game_manager.get_game(ctx.channel.id)
    if not game:
        await ctx.send("No game is currently active!")
        return

    cards = game.draw_cards(ctx.author.id)
    if cards:
        cards_text = "\n".join([f"{i+1}. {card}" for i, card in enumerate(cards)])
        await ctx.author.send(f"Your cards:\n{cards_text}")
        await ctx.send(f"Cards have been sent to {ctx.author.name} via DM!")
    else:
        await ctx.send("You're not in the game or already have cards!")

@bot.command(name='play', help='Play a card from your hand')
async def play_card(ctx, card_number: int):
    """Play a card from your hand"""
    try:
        if isinstance(card_number, str):
            card_number = int(card_number)

        if not ctx.author.voice:
            logger.debug(f"User {ctx.author.name} not in voice channel")
            await ctx.send("You need to stay in the voice channel to play!")
            return

        game = game_manager.get_game(ctx.channel.id)
        if not game:
            logger.debug(f"No active game in channel {ctx.channel.name}")
            await ctx.send("No game is currently active!")
            return

        success = game.play_card(ctx.author.id, card_number - 1)
        if success:
            await ctx.send(f"{ctx.author.name} has played their card!")
            db.log_card_play(ctx.channel.id, ctx.author.id, card_number)
        else:
            logger.debug(f"Failed to play card {card_number} for user {ctx.author.name}")
            await ctx.send("Invalid card number or it's not your turn!")
    except ValueError:
        logger.error(f"Invalid card number format: {card_number}")
        await ctx.send("Please provide a valid card number (e.g., `.cah play 1`)")
    except Exception as e:
        logger.error(f"Error in play_card command: {str(e)}")
        await ctx.send("An error occurred while playing your card. Please try again.")

@bot.command(name='show', help='Show all played cards')
async def show_played_cards(ctx):
    """Show all played cards for selection"""
    if not ctx.author.voice:
        logger.debug(f"User {ctx.author.name} not in voice channel")
        await ctx.send("You need to be in a voice channel to play!")
        return

    game = game_manager.get_game(ctx.channel.id)
    if not game:
        logger.debug(f"No active game in channel {ctx.channel.name}")
        await ctx.send("No game is currently active!")
        return

    if ctx.author.id != game.current_prompt_drawer:
        await ctx.send("Only the current prompt drawer can view played cards!")
        return

    played_cards = game.get_played_cards()
    if not played_cards:
        await ctx.send("No cards have been played yet!")
        return

    cards_text = "\n".join([f"{i+1}. {card_info['card']} (played by {card_info['player_name']})"
                           for i, (_, card_info) in enumerate(played_cards.items())])
    await ctx.send(f"**Played Cards**:\n{cards_text}\n\nUse `.cah win <number>` to choose the winning card!")

@bot.command(name='win', help='Select winning card')
async def select_winner(ctx, card_number: int):
    """Select the winning card for the round"""
    try:
        if isinstance(card_number, str):
            card_number = int(card_number)

        if not ctx.author.voice:
            logger.debug(f"User {ctx.author.name} not in voice channel")
            await ctx.send("You need to be in a voice channel to play!")
            return

        game = game_manager.get_game(ctx.channel.id)
        if not game:
            logger.debug(f"No active game in channel {ctx.channel.name}")
            await ctx.send("No game is currently active!")
            return

        if ctx.author.id != game.current_prompt_drawer:
            await ctx.send("Only the current prompt drawer can select the winning card!")
            return

        played_cards = list(game.get_played_cards().items())
        if not played_cards or card_number < 1 or card_number > len(played_cards):
            logger.debug(f"Invalid card selection: {card_number}, available cards: {len(played_cards)}")
            await ctx.send("Invalid card number!")
            return

        winning_player_id = played_cards[card_number - 1][0]
        winning_card = played_cards[card_number - 1][1]

        if game.select_winner(winning_player_id):
            await ctx.send(f"🎉 **Winner**: {winning_card['player_name']} with \"{winning_card['card']}\"!")

            # Show current scores
            scores = game.get_scores()
            scores_text = "\n".join([f"{info['name']}: {info['score']} points" for info in scores.values()])
            await ctx.send(f"**Current Scores**:\n{scores_text}")

            # Announce next prompt drawer
            next_drawer = game.players[game.current_prompt_drawer]['name']
            await ctx.send(f"\n👉 {next_drawer} will draw the next black card!")
        else:
            logger.error(f"Failed to select winner for card {card_number}")
            await ctx.send("Error selecting winner!")
    except ValueError:
        logger.error(f"Invalid card number format: {card_number}")
        await ctx.send("Please provide a valid card number (e.g., `.cah win 1`)")
    except Exception as e:
        logger.error(f"Error in select_winner command: {str(e)}")
        await ctx.send("An error occurred while selecting the winner. Please try again.")

@bot.command(name='score', help='Show current scores')
async def show_scores(ctx):
    """Show current game scores"""
    game = game_manager.get_game(ctx.channel.id)
    if not game:
        await ctx.send("No game is currently active!")
        return

    scores = game.get_scores()
    scores_text = "\n".join([f"{info['name']}: {info['score']} points" for info in scores.values()])
    await ctx.send(f"**Current Scores**:\n{scores_text}")

@bot.command(name='end', help='End the current game')
async def end_game(ctx):
    """End the current game"""
    game = game_manager.get_game(ctx.channel.id)
    if not game:
        await ctx.send("No game is currently active!")
        return

    # Show final scores and winner
    scores = game.get_scores()
    scores_text = "\n".join([f"{info['name']}: {info['score']} points" for info in scores.values()])
    await ctx.send(f"**Final Scores**:\n{scores_text}")

    winner = game.get_winner()
    if winner:
        await ctx.send(f"\n🎉 **WINNER**: {winner['name']} with {winner['score']} points! 🎉")

    if game_manager.end_game(ctx.channel.id):
        await ctx.send("Game ended! Thanks for playing!")
        db.log_game_end(ctx.channel.id)
    else:
        await ctx.send("Error ending game!")

@bot.command(name='r', help='Show game rules and commands')
async def show_rules(ctx):
    """Show game rules and commands"""
    rules_text = """
**Cards Against Humanity - Voice Chat Edition**
*A party game for horrible people, now in Discord!*

**How to Play:**
1. Join a voice channel
2. Use `.cah s` to start a new game
3. Others in the voice channel use `.cah j` to join
4. Each round:
   - One player uses `.cah p` to draw a black card
   - Other players use `.cah d` to get their white cards (via DM)
   - Players play cards with `.cah play <number>`
   - Prompt drawer uses `.cah show` to see cards
   - Prompt drawer picks winner with `.cah win <number>`

**Commands:**
`.cah s` - Start game
`.cah j` - Join game
`.cah p` - Draw black card prompt
`.cah d` - Draw white cards
`.cah play <number>` - Play a card
`.cah show` - Show played cards
`.cah win <number>` - Select winner
`.cah score` - Show scores
`.cah end` - End game
`.cah r` - Show this help
    """
    await ctx.send(rules_text)

@bot.command(name='p', help='Draw a black card prompt')
async def draw_prompt(ctx):
    """Draw a black prompt card for the current round"""
    logger.debug(f"Prompt command requested by {ctx.author.name}")

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

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors with helpful messages"""
    if isinstance(error, commands.CommandNotFound):
        # Suggest help command for unknown commands
        command = ctx.message.content.split()[0] if ctx.message.content else 'Unknown'
        logger.warning(f"User {ctx.author.name} attempted to use unknown command: {command}")
        await ctx.send(f"Command not found. Use `.cah r` to see all available commands.\nMake sure to use the `.cah` prefix, for example: `.cah s` to start a game.")
    elif isinstance(error, commands.MissingRequiredArgument):
        # Help with command syntax
        await ctx.send(f"Missing required argument for command. Example: `.cah {ctx.command.name} <number>`")
    else:
        # Log other errors
        logger.error(f"Error executing command {ctx.command}: {str(error)}")
        await ctx.send("An error occurred while processing your command. Please try again.")

@bot.event
async def on_command(ctx):
    """Log successful command usage"""
    logger.info(f"Command {ctx.command.name} used by {ctx.author.name} in channel {ctx.channel.name}")

bot.run(token)