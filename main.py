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

@bot.command(name='config', help='Configure game settings')
async def configure_game(ctx, setting: str, value: str):
    """Configure game settings like NSFW content"""
    if setting.lower() != "nsfw":
        await ctx.send("Available settings: 'nsfw' (values: on/off)")
        return

    value = value.lower()
    if value not in ['on', 'off']:
        await ctx.send("Please use 'on' or 'off' as the value")
        return

    channel_id = ctx.channel.id
    game = game_manager.get_game(channel_id)

    if not game:
        await ctx.send("No active game. Start a new game first with `.cah s`")
        return

    # Update NSFW setting
    allow_nsfw = (value == 'on')
    if game.update_nsfw_setting(allow_nsfw):
        status = "enabled" if allow_nsfw else "disabled"
        await ctx.send(f"NSFW content {status} for the current game")

        # Notify players about their updated cards
        for player_id in game.players:
            try:
                user = await bot.fetch_user(player_id)
                cards = game.players[player_id]['cards']
                cards_text = "\n".join([f"{i+1}. {card}" for i, card in enumerate(cards)])
                await user.send(f"Your cards have been updated due to NSFW setting change:\n{cards_text}")
            except Exception as e:
                logger.error(f"Failed to send updated cards to player {player_id}: {str(e)}")

        # If a black card was filtered, notify channel
        if game.current_black_card is None and game.round_in_progress:
            await ctx.send("The current black card has been filtered. Please draw a new black card with `.cah p`")
    else:
        await ctx.send("NSFW setting is already set to that value")

@bot.command(name='s', help='Start a new game')
async def start_game(ctx, *args):
    """Start a new game of Cards Against Humanity"""
    if not ctx.author.voice:
        await ctx.send("You need to be in a voice channel to start a game!")
        return

    if game_manager.is_game_active(ctx.channel.id):
        await ctx.send("A game is already in progress!")
        return

    # Check for NSFW flag
    allow_nsfw = False
    if len(args) > 0 and args[0].lower() == "nsfw":
        allow_nsfw = True

    game_manager.create_game(ctx.channel.id, allow_nsfw)
    nsfw_status = "NSFW content enabled" if allow_nsfw else "NSFW content disabled"
    await ctx.send(f"New game started! {nsfw_status}\nPlayers in the voice channel can join using `.cah j`")
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
        # Send initial instructions via DM
        await ctx.author.send("Welcome to Cards Against Humanity! You'll play the game through DMs.\nUse `.cah d` to draw your cards.")
        db.log_player_join(ctx.channel.id, ctx.author.id)
    else:
        await ctx.send("You're already in the game!")

@bot.command(name='d', help='Draw white cards')
async def draw_cards(ctx):
    """Draw your hand of white cards"""
    # Find the relevant game if command was sent in DM
    game = None
    if isinstance(ctx.channel, discord.DMChannel):
        for channel_id, g in game_manager.games.items():
            if ctx.author.id in g.players:
                game = g
                break
    else:
        # Voice check only if in a server channel
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

        # If in a server channel, also send confirmation there
        if not isinstance(ctx.channel, discord.DMChannel):
            await ctx.send(f"Cards have been sent to {ctx.author.name} via DM!")
    else:
        await ctx.send("You're not in the game or already have cards!")

@bot.command(name='play', help='Play a card from your hand')
async def play_card(ctx, card_number: int):
    try:
        if isinstance(card_number, str):
            card_number = int(card_number)

        # Find the relevant game
        game = None
        if isinstance(ctx.channel, discord.DMChannel):
            for channel_id, g in game_manager.games.items():
                if ctx.author.id in g.players:
                    game = g
                    break
        else:
            game = game_manager.get_game(ctx.channel.id)

        if not game:
            await ctx.send("No active game found!")
            return

        result = game.play_card(ctx.author.id, card_number - 1)
        if result == "all_played":
            await send_game_message(ctx, f"{ctx.author.name} has played their card!", game_update=True)

            # Get prompt drawer and send them a DM with played cards
            prompt_drawer = await bot.fetch_user(game.current_prompt_drawer)
            played_cards = game.get_played_cards(include_players=True)  # Get cards with player names
            cards_text = "\n".join([f"{i+1}. {card_info['card']}"
                                  for i, (_, card_info) in enumerate(played_cards.items())])

            dm_text = (
                f"**Current Black Card**: {game.current_black_card['text']}\n\n"
                "**All cards have been played! Here are the answers:**\n"
                f"{cards_text}\n\n"
                "Read these answers aloud in voice chat and then use `.cah win <number>` to choose the winning card!"
            )
            await prompt_drawer.send(dm_text)

            # Send update to game channel
            if isinstance(ctx.channel, discord.DMChannel):
                for channel_id in game_manager.games:
                    if game == game_manager.get_game(channel_id):
                        channel = bot.get_channel(channel_id)
                        if channel:
                            await channel.send("All players have played their cards! Waiting for the prompt drawer to read the answers and select a winner...")

        elif result:
            await send_game_message(ctx, f"{ctx.author.name} has played their card!", game_update=True)
        else:
            await ctx.send("Invalid card number or it's not your turn!")

    except ValueError:
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

        # Find the relevant game if command was sent in DM
        game = None
        channel_id = None
        if isinstance(ctx.channel, discord.DMChannel):
            for c_id, g in game_manager.games.items():
                if ctx.author.id in g.players:
                    game = g
                    channel_id = c_id
                    break
        else:
            # Voice check only if in a server channel
            if not ctx.author.voice:
                logger.debug(f"User {ctx.author.name} not in voice channel")
                await ctx.send("You need to be in a voice channel to play!")
                return
            game = game_manager.get_game(ctx.channel.id)
            channel_id = ctx.channel.id

        if not game:
            await ctx.send("No game is currently active!")
            return

        if ctx.author.id != game.current_prompt_drawer:
            await ctx.send("Only the current prompt drawer can select the winning card!")
            return

        played_cards = game.get_played_cards(include_players=True)
        played_cards_list = list(played_cards.items())
        if not played_cards_list or card_number < 1 or card_number > len(played_cards_list):
            logger.debug(f"Invalid card selection: {card_number}, available cards: {len(played_cards_list)}")
            await ctx.send("Invalid card number!")
            return

        winning_player_id = played_cards_list[card_number - 1][0]
        winning_card = played_cards_list[card_number - 1][1]

        if game.select_winner(winning_player_id):
            # First announce the winner
            await ctx.send(f"🎉 **Winner**: {winning_card['player_name']} with \"{winning_card['card']}\"!")

            # Also announce to the game channel if command was in DM
            if isinstance(ctx.channel, discord.DMChannel) and channel_id:
                try:
                    game_channel = bot.get_channel(channel_id)
                    if game_channel:
                        await game_channel.send(f"🎉 **Winner**: {winning_card['player_name']} with \"{winning_card['card']}\"!")
                except Exception as e:
                    logger.error(f"Failed to send winner announcement to game channel: {str(e)}")

            # Then reveal all played cards
            cards_text = "\n".join([f"• {info['player_name']}: {info['card']}"
                                  for _, info in played_cards.items()])
            await ctx.send(f"**All Played Cards**:\n{cards_text}")

            # Show current scores
            scores = game.get_scores()
            scores_text = "\n".join([f"{info['name']}: {info['score']} points" for info in scores.values()])
            await ctx.send(f"**Current Scores**:\n{scores_text}")

            # Announce next prompt drawer
            next_drawer = game.players[game.current_prompt_drawer]['name']
            await ctx.send(f"\n👉 {next_drawer} will draw the next black card!")
            try:
                user = await bot.fetch_user(game.current_prompt_drawer)
                await user.send(f"It's your turn to draw the next black card! Use `.cah p`")
            except Exception as e:
                logger.error(f"Failed to notify next prompt drawer {game.current_prompt_drawer}: {str(e)}")

            # Notify players about their topped-up cards via DM
            for player_id in game.players:
                if player_id != game.current_prompt_drawer:
                    try:
                        user = await bot.fetch_user(player_id)
                        cards = game.players[player_id]['cards']
                        cards_text = "\n".join([f"{i+1}. {card}" for i, card in enumerate(cards)])
                        await user.send(f"Your cards have been topped up:\n{cards_text}")
                    except Exception as e:
                        logger.error(f"Failed to send updated cards to player {player_id}: {str(e)}")
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
2. Use `.cah s` to start a new game (add 'nsfw' to enable NSFW content)
3. Others in the voice channel use `.cah j` to join
4. Each round:
   - One player uses `.cah p` to draw a black card
   - Other players get their white cards via DM
   - Players either:
     • Play a card with `.cah play <number>`
     • Or submit a custom answer with `.cah custom <your answer>`
   - Prompt drawer gets answers in DM to read aloud and select winner
   - Prompt drawer picks winner with `.cah win <number>`

**Commands:**
`.cah s` - Start game
`.cah s nsfw` - Start game with NSFW content
`.cah j` - Join game
`.cah p` - Draw black card prompt
`.cah play <number>` - Play a card
`.cah custom <answer>` - Submit your own custom answer (Example: `.cah custom A really funny answer`)
`.cah win <number>` - Select winner
`.cah score` - Show scores
`.cah config nsfw on/off` - Toggle NSFW content
`.cah end` - End game
`.cah r` - Show this help
`.cah exit` - Exit game

**Custom Card Management:**
`.cah save <white/black> <text>` - Save a custom card to the game database
`.cah list [white/black]` - List custom cards (Mod only)
`.cah approve <white/black> <text>` - Approve custom card for permanent use (Mod only)
`.cah remove <white/black> <text>` - Remove inappropriate cards from game (Mod only)

*Note: Custom answers (using `.cah custom`) are marked with ✏️ when displayed to the prompt drawer.*
*Custom cards (using `.cah save`) are saved to the database and can be drawn by players in future games.*

*Note: All players automatically play through DMs for a better experience!*
    """
    await ctx.send(rules_text)

@bot.command(name='p', help='Draw a black card prompt')
async def draw_prompt(ctx):
    """Draw a black prompt card for the current round"""
    logger.debug(f"Prompt command requested by {ctx.author.name}")

    # Find the relevant game if command was sent in DM
    game = None
    channel_id = None
    if isinstance(ctx.channel, discord.DMChannel):
        for c_id, g in game_manager.games.items():
            if ctx.author.id in g.players:
                game = g
                channel_id = c_id
                break

        # In DM, check if this player is the prompt drawer
        if game and game.current_prompt_drawer != ctx.author.id:
            await ctx.send("Only the current prompt drawer can draw a black card!")
            return
    else:
        # Voice check only if in a server channel
        if not ctx.author.voice:
            logger.debug(f"User {ctx.author.name} not in voice channel")
            await ctx.send("You need to be in a voice channel to play!")
            return
        game = game_manager.get_game(ctx.channel.id)
        channel_id = ctx.channel.id

        # In server channel, check if this player is the prompt drawer
        if game and game.current_prompt_drawer != ctx.author.id:
            await ctx.send(f"Only the current prompt drawer ({game.players[game.current_prompt_drawer]['name']}) can draw a black card!")
            return

    if not game:
        await ctx.send("No game is currently active!")
        return

    # Don't allow drawing a new card if a round is in progress
    if game.round_in_progress and game.current_black_card:
        await ctx.send(f"A round is already in progress! Current black card: {game.current_black_card['text']}")
        return

    black_card = game.start_round()
    if black_card:
        logger.info(f"Drew black card: {black_card}")

        # Send to the game channel if command was in DM
        if isinstance(ctx.channel, discord.DMChannel) and channel_id:
            try:
                game_channel = bot.get_channel(channel_id)
                if game_channel:
                    await game_channel.send(f"📜 **Black Card**: {black_card}")
            except Exception as e:
                logger.error(f"Failed to send black card to game channel: {str(e)}")

        await ctx.send(f"📜 **Black Card**: {black_card}")

        # Notify all other players to play their cards
        for player_id in game.players:
            if player_id != game.current_prompt_drawer:
                try:
                    user = await bot.fetch_user(player_id)
                    await user.send(f"📜 **New Black Card**: {black_card}\n\nUse `.cah play <number>` to play a card from your hand!")
                except Exception as e:
                    logger.error(f"Failed to send notification to player {player_id}: {str(e)}")
    else:
        logger.warning("No black cards available")
        await ctx.send("No more black cards available!")


@bot.command(name='exit', help='Exit the current game')
async def exit_game(ctx):
    """Exit the current game"""
    # Check all channels where the player might be in a game
    for channel_id, game in game_manager.games.items():
        if ctx.author.id in game.players:
            # Remove player from game
            if game.remove_player(ctx.author.id):
                # If command was sent in DM, notify the game channel
                if isinstance(ctx.channel, discord.DMChannel):
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(f"{ctx.author.name} has left the game!")
                await ctx.send("You've left the game!")
                return

    await ctx.send("You're not in any active games!")


async def send_game_message(ctx, content, game_update=False):
    """Send message to appropriate channel(s)"""
    if isinstance(ctx.channel, discord.DMChannel):
        # Find the game channel
        for channel_id, game in game_manager.games.items():
            if ctx.author.id in game.players:
                if game_update:
                    # Send game updates to main channel
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(content)
                await ctx.send(content)
                return
    else:
        await ctx.send(content)

@bot.event
async def on_message(message):
    """Handle commands in DMs"""
    # Don't respond to bot messages
    if message.author == bot.user:
        return

    # Check if message is a DM and starts with the command prefix
    if isinstance(message.channel, discord.DMChannel):
        # Make sure we only process commands with the correct prefix
        if message.content.startswith(('.cah ', '!cah ')):
            # Find if player is in any active games
            for channel_id, game in game_manager.games.items():
                if message.author.id in game.players:
                    # Process the command
                    ctx = await bot.get_context(message)
                    if ctx.command is None:
                        # Log the invalid command attempt
                        command_name = message.content.split(' ')[1] if len(message.content.split(' ')) > 1 else 'unknown'
                        logger.warning(f"Invalid command in DM: {command_name} by {message.author.name}")
                        await message.channel.send(f"Command not found. Use `.cah r` to see all available commands.")
                    else:
                        await bot.invoke(ctx)
                    return

    # Process regular commands
    await bot.process_commands(message)

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
    if isinstance(ctx.channel, discord.DMChannel):
        logger.info(f"Command {ctx.command.name} used by {ctx.author.name} in DM")
    else:
        logger.info(f"Command {ctx.command.name} used by {ctx.author.name} in channel {ctx.channel.name}")

@bot.command(name='custom', aliases=['c'], help='Play a custom answer instead of a card')
async def play_custom_answer(ctx, *, answer: str):
    """Play a custom answer instead of using a card from your hand"""
    try:
        # Find the relevant game
        game = None
        if isinstance(ctx.channel, discord.DMChannel):
            for channel_id, g in game_manager.games.items():
                if ctx.author.id in g.players:
                    game = g
                    break
        else:
            game = game_manager.get_game(ctx.channel.id)

        if not game:
            await ctx.send("No active game found!")
            return

        result = game.play_custom_answer(ctx.author.id, answer)
        if result == "all_played":
            await send_game_message(ctx, f"{ctx.author.name} has played their custom answer!", game_update=True)

            # Get prompt drawer and send them a DM with played cards/answers
            prompt_drawer = await bot.fetch_user(game.current_prompt_drawer)
            played_cards = game.get_played_cards(include_players=True, include_custom=True)

            # Format for the prompt drawer to display
            cards_text = []
            i = 1
            for player_id, info in played_cards.items():
                prefix = "✏️ " if player_id in game.custom_answers else ""
                cards_text.append(f"{i}. {prefix}{info['card']}")
                i += 1

            cards_text = "\n".join(cards_text)

            dm_text = (
                f"**Current Black Card**: {game.current_black_card['text']}\n\n"
                "**All answers have been submitted! Here they are:**\n"
                f"{cards_text}\n\n"
                "Read these answers aloud in voice chat and then use `.cah win <number>` to choose the winning answer!"
            )
            await prompt_drawer.send(dm_text)

            # Send update to game channel
            if isinstance(ctx.channel, discord.DMChannel):
                for channel_id in game_manager.games:
                    if game == game_manager.get_game(channel_id):
                        channel = bot.get_channel(channel_id)
                        if channel:
                            await channel.send("All players have submitted their answers! Waiting for the prompt drawer to read them and select a winner...")

        elif result:
            await send_game_message(ctx, f"{ctx.author.name} has played their custom answer!", game_update=True)
            await ctx.send("Your custom answer has been submitted!")
        else:
            await ctx.send("You can't play right now!")

    except Exception as e:
        logger.error(f"Error in play_custom_answer command: {str(e)}")
        await ctx.send("An error occurred while submitting your answer. Please try again.")

@bot.command(name='save', help='Save a custom answer to the game')
async def save_custom_answer(ctx, card_type: str, *, card_text: str):
    """Save a custom answer to be used in future games"""
    if card_type.lower() not in ['white', 'black']:
        await ctx.send("Please specify either 'white' or 'black' as the card type!")
        return

    game = game_manager.get_game(ctx.channel.id)
    if not game:
        await ctx.send("No active game found!")
        return

    if game.add_custom_card(card_text, card_type.lower(), ctx.author.id):
        await ctx.send(f"Custom {card_type} card saved! It will be available after moderator approval.")
    else:
        await ctx.send("Failed to save custom card. It might already exist.")

@bot.command(name='approve', help='Approve a custom card (Moderators only)')
@commands.has_permissions(manage_messages=True)
async def approve_card(ctx, card_type: str, *, card_text: str):
    """Approve a custom card for use in games"""
    if card_type.lower() not in ['white', 'black']:
        await ctx.send("Please specify either 'white' or 'black' as the card type!")
        return

    game = game_manager.get_game(ctx.channel.id)
    if not game:
        # Create temporary game instance for card management
        game_manager.create_game(ctx.channel.id)
        game = game_manager.get_game(ctx.channel.id)

    if game.approve_custom_card(card_text, card_type.lower(), ctx.author.id):
        await ctx.send(f"Custom {card_type} card approved! It will now appear in games.")
    else:
        await ctx.send("Failed to approve card. It might not exist or is already approved.")

@bot.command(name='remove', help='Remove a card from the game (Moderators only)')
@commands.has_permissions(manage_messages=True)
async def remove_card(ctx, card_type: str, *, card_text: str):
    """Remove a card from the game"""
    if card_type.lower() not in ['white', 'black']:
        await ctx.send("Please specify either 'white' or 'black' as the card type!")
        return

    game = game_manager.get_game(ctx.channel.id)
    if not game:
        # Create temporary game instance for card management
        game_manager.create_game(ctx.channel.id)
        game = game_manager.get_game(ctx.channel.id)

    if game.remove_card(card_text, card_type.lower(), ctx.author.id):
        await ctx.send(f"{card_type.capitalize()} card removed from the game.")
    else:
        await ctx.send("Failed to remove card. It might not exist or is already removed.")

@bot.command(name='list', help='List custom cards (Moderators only)')
@commands.has_permissions(manage_messages=True)
async def list_custom_cards(ctx, card_type: str = None, show_all: bool = False):
    """List custom cards"""
    if card_type and card_type.lower() not in['white', 'black']:
        await ctx.send("Please specify either 'white' or 'black' as the card type!")
        return

    types = ['white', 'black'] if not card_type else [card_type.lower()]
    for t in types:
        custom_cards = db.get_custom_cards(t, only_approved=not show_all)
        if custom_cards:
            cards_text = "\n".join([f"• {card}" for card in custom_cards])
            title = f"Custom {t.capitalize()} Cards"
            if show_all:
                title += " (Including Unapproved)"
            await ctx.send(f"**{title}**:\n{cards_text}")
        else:
            await ctx.send(f"No custom {t} cards found.")

# Get Discord token and run bot
token = os.getenv('DISCORD_TOKEN')
if not token:
    logger.error("No Discord token found!")
    raise ValueError("Please set the DISCORD_TOKEN environment variable")

bot.run(token)