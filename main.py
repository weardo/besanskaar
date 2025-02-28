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
from discord import app_commands, Embed, Color, ButtonStyle
from discord.ui import Button, View
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
    
    # Check for any active games with players who need prompt notification
    for channel_id, game in game_manager.games.items():
        for player_id, player in game.players.items():
            if player.get('needs_prompt_notification') and player_id == game.current_prompt_drawer:
                try:
                    user = await bot.fetch_user(player_id)
                    channel = bot.get_channel(channel_id)
                    if user and channel:
                        await notify_prompt_drawer(user, channel.name)
                except Exception as e:
                    logger.error(f"Failed to send prompt notification on startup: {str(e)}")

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

    # Initialize database for the game
    game_manager.database = db  
    game_manager.create_game(ctx.channel.id, allow_nsfw)
    nsfw_status = "NSFW content enabled" if allow_nsfw else "NSFW content disabled"

    # Create a fancy embed for game start
    embed = Embed(
        title="🎮 Cards Against Humanity - New Game!", 
        description=f"A new game has been started by {ctx.author.display_name}!\n\n**{nsfw_status}**", 
        color=Color.purple()
    )
    embed.add_field(name="How to Join", value="Click the button below or type `.cah j`", inline=False)
    embed.set_footer(text="Join a voice channel to play!")

    # Create buttons for common actions
    view = View(timeout=None)
    join_button = Button(style=ButtonStyle.green, label="Join Game", emoji="👋", custom_id="join_game")
    rules_button = Button(style=ButtonStyle.blurple, label="Show Rules", emoji="📜", custom_id="show_rules")

    async def join_callback(interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("You need to be in a voice channel to join!", ephemeral=True)
            return

        # Create proper context and join game
        ctx = await bot.get_context(interaction.message, cls=commands.Context)
        ctx.author = interaction.user  # Set correct author for voice channel check
        await join_game(ctx)

    async def rules_callback(interaction):
        await show_rules(await bot.get_context(interaction.message, cls=commands.Context))

    join_button.callback = join_callback
    rules_button.callback = rules_callback

    view.add_item(join_button)
    view.add_item(rules_button)

    await ctx.send(embed=embed, view=view)
    db.log_game_start(ctx.channel.id, ctx.author.id)
    
    # Add the creator as first player
    game_manager.add_player(ctx.channel.id, ctx.author.id, ctx.author.name)
    
    # Notify the first prompt drawer (which is the first player) that it's their turn
    game = game_manager.get_game(ctx.channel.id)
    if game and game.current_prompt_drawer == ctx.author.id:
        await notify_prompt_drawer(ctx.author, ctx.channel.name)

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
        # Channel notification
        embed = Embed(
            title="Player Joined", 
            description=f"**{ctx.author.name}** has joined the game!", 
            color=Color.green()
        )
        await ctx.send(embed=embed)

        # Get the game to check if this player is the prompt drawer
        game = game_manager.get_game(ctx.channel.id)
        is_prompt_drawer = game and game.current_prompt_drawer == ctx.author.id
        
        # Create DM welcome message with buttons
        dm_embed = Embed(
            title="🃏 Welcome to Cards Against Humanity!", 
            description=(
                "You'll play the game through DMs for privacy.\n\n" +
                ("You are the current prompt drawer! Draw a black card to start the round." 
                 if is_prompt_drawer else
                 "Click the button below to draw your cards and begin playing!")
            ),
            color=Color.blue()
        )

        dm_view = View(timeout=None)
        
        if is_prompt_drawer:
            # If this player is the prompt drawer, show a button to draw a black card
            draw_prompt_button = Button(
                style=ButtonStyle.green, 
                label="Draw Black Card", 
                emoji="🎲", 
                custom_id="draw_black_card"
            )
            
            async def draw_prompt_callback(interaction):
                try:
                    ctx = await bot.get_context(interaction.message, cls=commands.Context)
                    ctx.author = interaction.user
                    await draw_prompt(ctx)
                except Exception as e:
                    logger.error(f"Error in draw prompt button: {str(e)}")
                    await interaction.response.send_message("An error occurred. Please try typing `.cah p` instead.", ephemeral=True)
                    
            draw_prompt_button.callback = draw_prompt_callback
            dm_view.add_item(draw_prompt_button)
            
            # Also send a separate notification
            await notify_prompt_drawer(ctx.author, ctx.channel.name)
        else:
            # Regular player gets the draw cards button
            draw_button = Button(
                style=ButtonStyle.green, 
                label="Draw Cards", 
                emoji="🃏", 
                custom_id="draw_cards"
            )

            async def draw_callback(interaction):
                try:
                    # Create a proper context with the right user and channel info
                    ctx = await bot.get_context(interaction.message, cls=commands.Context)
                    ctx.author = interaction.user  # Set correct author for user check
                    
                    # Call the draw_cards function with the properly set context
                    await draw_cards(ctx)
                except Exception as e:
                    logger.error(f"Error in draw cards button: {str(e)}")
                    await interaction.response.send_message("An error occurred. Please try typing `.cah d` instead.", ephemeral=True)

            draw_button.callback = draw_callback
            dm_view.add_item(draw_button)

        await ctx.author.send(embed=dm_embed, view=dm_view)
        db.log_player_join(ctx.channel.id, ctx.author.id)
    else:
        await ctx.send("You're already in the game!")

@bot.command(name='d', help='Draw white cards')
async def draw_cards(ctx):
    """Draw your hand of white cards"""
    # Find the relevant game if command was sent in DM
    game = None
    if isinstance(ctx.channel, discord.DMChannel):
        # Check all games to find one where the player is registered
        player_found = False
        for channel_id, g in game_manager.games.items():
            if ctx.author.id in g.players:
                game = g
                player_found = True
                break
        
        if not player_found:
            await ctx.send("You're not currently in any active game! Join a game first with `.cah j` in a server channel.")
            return
    else:
        # Voice check only if in a server channel
        if not ctx.author.voice:
            await ctx.send("You need to stay in the voice channel to play!")
            return
        
        # Check if game exists in this channel
        game = game_manager.get_game(ctx.channel.id)
        if not game:
            await ctx.send("No game is currently active in this channel! Start one with `.cah s`")
            return
            
        # Check if player is in the game
        if ctx.author.id not in game.players:
            await ctx.send("You're not in this game! Join first with `.cah j`")
            return

    # At this point we have verified the game exists and player is part of it
    try:
        cards = game.draw_cards(ctx.author.id)
        if not cards:
            await ctx.send("You already have a full hand of cards!")
            return
            
        # Create a fancy card display
        embed = Embed(
            title="🃏 Your Cards", 
            description="Here are your white cards. Play one with the buttons below when it's your turn.", 
            color=Color.gold()
        )

        # Add each card as a field for better readability
        for i, card in enumerate(cards):
            embed.add_field(name=f"Card {i+1}", value=card, inline=False)

        # Create buttons for playing cards
        view = View(timeout=None)

        # Add buttons to play each card (up to 5 per row)
        for i in range(len(cards)):
            card_button = Button(
                style=ButtonStyle.gray, 
                label=f"Play #{i+1}", 
                custom_id=f"play_card_{i+1}"
            )

            # This is a factory function to capture the card index correctly
            def create_callback(index):
                async def play_card_callback(interaction):
                    try:
                        ctx = await bot.get_context(interaction.message, cls=commands.Context)
                        ctx.author = interaction.user  # Ensure author is set correctly
                        await play_card(ctx, index)
                    except Exception as e:
                        logger.error(f"Error in play card button: {str(e)}")
                        await interaction.response.send_message("An error occurred. Please try typing `.cah play {index}` instead.", ephemeral=True)
                return play_card_callback

            card_button.callback = create_callback(i+1)
            view.add_item(card_button)

        # Add a custom answer button
        custom_button = Button(style=ButtonStyle.blurple, label="Custom Answer", custom_id="custom_answer")

        async def custom_callback(interaction):
            custom_modal = discord.ui.Modal(title="Your Custom Answer")
            custom_text = discord.ui.TextInput(
                label="Your answer",
                placeholder="Type your funny answer here...",
                style=discord.TextStyle.paragraph
            )
            custom_modal.add_item(custom_text)

            async def modal_callback(interaction):
                try:
                    ctx = await bot.get_context(interaction.message, cls=commands.Context)
                    ctx.author = interaction.user  # Ensure author is set correctly
                    await play_custom_answer(ctx, answer=custom_text.value)
                    await interaction.response.send_message("Custom answer submitted!", ephemeral=True)
                except Exception as e:
                    logger.error(f"Error in custom answer modal: {str(e)}")
                    await interaction.response.send_message("An error occurred. Please try typing `.cah c Your answer` instead.", ephemeral=True)

            custom_modal.on_submit = modal_callback
            await interaction.response.send_modal(custom_modal)

        custom_button.callback = custom_callback
        view.add_item(custom_button)

        await ctx.author.send(embed=embed, view=view)

        # If in a server channel, also send confirmation there
        if not isinstance(ctx.channel, discord.DMChannel):
            confirm_embed = Embed(
                title="Cards Drawn",
                description=f"Cards have been sent to {ctx.author.name} via DM!",
                color=Color.green()
            )
            await ctx.send(embed=confirm_embed)
    except Exception as e:
        logger.error(f"Error drawing cards: {str(e)}")
        await ctx.send(f"An error occurred while drawing cards: {str(e)}")

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
async def notify_prompt_drawer(user, channel_name=None):
    """Send a reminder to the prompt drawer that it's their turn"""
    # Create an attractive embed
    embed = Embed(
        title="🎮 Your Turn to Draw!", 
        description="It's your turn to draw a black card for the next round!", 
        color=Color.purple()
    )
    
    if channel_name:
        embed.add_field(
            name="Game Channel", 
            value=f"You're the prompt drawer in #{channel_name}", 
            inline=False
        )
    
    embed.add_field(
        name="What to Do", 
        value="Click the button below to draw a black card!", 
        inline=False
    )
    
    # Create a view with a button to draw the black card
    view = View(timeout=None)
    draw_button = Button(
        style=ButtonStyle.green, 
        label="Draw Black Card", 
        emoji="🎲", 
        custom_id="draw_black_card"
    )
    
    async def draw_callback(interaction):
        ctx = await bot.get_context(interaction.message, cls=commands.Context)
        ctx.author = interaction.user
        await draw_prompt(ctx)
        
    draw_button.callback = draw_callback
    view.add_item(draw_button)
    
    await user.send(embed=embed, view=view)
    logger.info(f"Sent prompt drawer notification to {user.name}")

async def select_winner(ctx, card_number: int = None):
    """Select the winning card for the round"""
    try:
        if isinstance(card_number, str) and card_number is not None:
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

        # If card_number is None, show all cards with buttons to select
        if card_number is None:
            if not played_cards_list:
                await ctx.send("No cards have been played yet!")
                return

            embed = Embed(
                title="🎮 Select Winner", 
                description=f"Select the best answer to: **{game.current_black_card['text']}**", 
                color=Color.blue()
            )

            # Show all cards
            for i, (_, card_info) in enumerate(played_cards_list):
                prefix = "✏️ " if _ in game.custom_answers else ""
                embed.add_field(
                    name=f"Card {i+1}", 
                    value=f"{prefix}{card_info['card']}", 
                    inline=False
                )

            # Create selection buttons
            view = View(timeout=None)

            # Add buttons for each card (up to 5 per row)
            for i in range(len(played_cards_list)):
                select_button = Button(
                    style=ButtonStyle.green, 
                    label=f"Select #{i+1}", 
                    custom_id=f"select_winner_{i+1}"
                )

                # Factory to capture card number correctly
                def create_callback(num):
                    async def select_callback(interaction):
                        ctx = await bot.get_context(interaction.message, cls=commands.Context)
                        await select_winner(ctx, num)
                    return select_callback

                select_button.callback = create_callback(i+1)
                view.add_item(select_button)

            await ctx.send(embed=embed, view=view)
            return

        # Process the winner selection if card_number is provided
        if not played_cards_list or card_number < 1 or card_number > len(played_cards_list):
            logger.debug(f"Invalid card selection: {card_number}, available cards: {len(played_cards_list)}")
            await ctx.send("Invalid card number!")
            return

        winning_player_id = played_cards_list[card_number - 1][0]
        winning_card = played_cards_list[card_number - 1][1]

        if game.select_winner(winning_player_id):
            # Create winner announcement embed
            winner_embed = Embed(
                title="🎉 Round Winner!", 
                description=f"**{winning_card['player_name']}** wins this round!", 
                color=Color.gold()
            )

            # Add the black card and winning answer
            winner_embed.add_field(
                name="Black Card", 
                value=game.current_black_card['text'], 
                inline=False
            )

            # Check if it was a custom answer
            prefix = "✏️ " if winning_player_id in game.custom_answers else ""
            winner_embed.add_field(
                name="Winning Answer", 
                value=f"{prefix}{winning_card['card']}", 
                inline=False
            )

            # First announce the winner
            await ctx.send(embed=winner_embed)

            # Also announce to the game channel if command was in DM
            if isinstance(ctx.channel, discord.DMChannel) and channel_id:
                try:
                    game_channel = bot.get_channel(channel_id)
                    if game_channel:
                        await game_channel.send(embed=winner_embed)
                except Exception as e:
                    logger.error(f"Failed to send winner announcement to game channel: {str(e)}")

            # Create an embed for all played cards
            cards_embed = Embed(
                title="📝 All Played Cards", 
                description="Here are all the cards that were played this round:", 
                color=Color.blue()
            )

            # Add each card as a field
            for player_id, info in played_cards.items():
                prefix = "✏️ " if player_id in game.custom_answers else ""
                cards_embed.add_field(
                    name=info['player_name'], 
                    value=f"{prefix}{info['card']}", 
                    inline=False
                )

            await ctx.send(embed=cards_embed)

            # Create an embed for scores
            scores = game.get_scores()
            scores_embed = Embed(
                title="🏆 Current Scores", 
                description="Here are the current standings:", 
                color=Color.teal()
            )

            # Add each player's score
            for player_id, info in scores.items():
                scores_embed.add_field(
                    name=info['name'], 
                    value=f"{info['score']} points", 
                    inline=True
                )

            await ctx.send(embed=scores_embed)

            # Announce next prompt drawer with a button
            next_drawer = game.players[game.current_prompt_drawer]['name']
            next_drawer_embed = Embed(
                title="Next Round", 
                description=f"👉 **{next_drawer}** will draw the next black card!", 
                color=Color.purple()
            )

            # Notify in the channel
            await ctx.send(embed=next_drawer_embed)

            # Send DM to next prompt drawer
            try:
                user = await bot.fetch_user(game.current_prompt_drawer)
                prompt_embed = Embed(
                    title="🎲 Your Turn!", 
                    description="It's your turn to draw the next black card!", 
                    color=Color.purple()
                )

                # Add button to draw card
                prompt_view = View(timeout=None)
                draw_button = Button(style=ButtonStyle.green, label="Draw Black Card", custom_id="draw_black_card")

                async def draw_callback(interaction):
                    ctx = await bot.get_context(interaction.message, cls=commands.Context)
                    await draw_prompt(ctx)

                draw_button.callback = draw_callback
                prompt_view.add_item(draw_button)

                await user.send(embed=prompt_embed, view=prompt_view)
            except Exception as e:
                logger.error(f"Failed to notify next prompt drawer {game.current_prompt_drawer}: {str(e)}")

            # Notify players about their topped-up cards via DM
            for player_id in game.players:
                if player_id != game.current_prompt_drawer:
                    try:
                        user = await bot.fetch_user(player_id)
                        cards = game.players[player_id]['cards']

                        cards_embed = Embed(
                            title="🃏 Cards Updated", 
                            description="Your cards have been topped up:", 
                            color=Color.gold()
                        )

                        # Add each card as a field
                        for i, card in enumerate(cards):
                            cards_embed.add_field(name=f"Card {i+1}", value=card, inline=False)

                        # Create buttons for playing cards
                        cards_view = View(timeout=None)

                        # Add buttons to play each card (up to 5 per row)
                        for i in range(len(cards)):
                            card_button = Button(
                                style=ButtonStyle.gray, 
                                label=f"Play #{i+1}", 
                                custom_id=f"play_card_{i+1}"
                            )

                            # This is a factory function to capture the card index correctly
                            def create_callback(index):
                                async def play_card_callback(interaction):
                                    ctx = await bot.get_context(interaction.message, cls=commands.Context)
                                    await play_card(ctx, index)
                                return play_card_callback

                            card_button.callback = create_callback(i+1)
                            cards_view.add_item(card_button)

                        # Add a custom answer button
                        custom_button = Button(style=ButtonStyle.blurple, label="Custom Answer", custom_id="custom_answer")

                        async def custom_callback(interaction):
                            custom_modal = discord.ui.Modal(title="Your Custom Answer")
                            custom_text = discord.ui.TextInput(
                                label="Your answer",
                                placeholder="Type your funny answer here...",
                                style=discord.TextStyle.paragraph
                            )
                            custom_modal.add_item(custom_text)

                            async def modal_callback(interaction):
                                ctx = await bot.get_context(interaction.message, cls=commands.Context)
                                await play_custom_answer(ctx, answer=custom_text.value)
                                await interaction.response.send_message("Custom answer submitted!", ephemeral=True)

                            custom_modal.on_submit = modal_callback
                            await interaction.response.send_modal(custom_modal)

                        custom_button.callback = custom_callback
                        cards_view.add_item(custom_button)

                        await user.send(embed=cards_embed, view=cards_view)
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

    # Create main rules embed
    rules_embed = Embed(
        title="🃏 Cards Against Humanity - Voice Chat Edition", 
        description="*A party game for horrible people, now in Discord!*", 
        color=Color.brand_red()
    )

    # Add sections as fields
    rules_embed.add_field(
        name="📋 How to Play",
        value=(
            "1️⃣ Join a voice channel\n"
            "2️⃣ Start game with buttons or `.cah s`\n"
            "3️⃣ Others join with buttons or `.cah j`\n"
            "4️⃣ Play rounds: black card → white cards → pick winner\n"
            "5️⃣ Winner gets a point, new round begins"
        ),
        inline=False
    )

    basic_commands = (
        "🎮 `.cah s` - Start game\n"
        "🎮 `.cah s nsfw` - Start with NSFW content\n"
        "👋 `.cah j` - Join game\n"
        "🎲 `.cah p` - Draw black card\n"
        "🃏 `.cah play <number>` - Play a card\n"
        "✏️ `.cah c <answer>` - Submit custom answer\n"
        "🏆 `.cah win <number>` - Select winner\n"
        "📊 `.cah score` - Show scores\n"
        "⚙️ `.cah config nsfw on/off` - Toggle NSFW\n"
        "🚪 `.cah exit` - Leave game\n"
        "🛑 `.cah end` - End game"
    )

    rules_embed.add_field(
        name="🎮 Basic Commands",
        value=basic_commands,
        inline=False
    )

    # Create a separate embed for custom card commands
    custom_embed = Embed(
        title="✨ Custom Card Management", 
        color=Color.gold()
    )

    custom_commands = (
        "💾 `.cah save <white/black> <text>` - Save custom card\n"
        "📋 `.cah list [white/black]` - List custom cards (Mod only)\n"
        "✅ `.cah approve <white/black> <text>` - Approve custom card (Mod only)\n"
        "❌ `.cah remove <white/black> <text>` - Remove card (Mod only)"
    )

    custom_embed.add_field(
        name="Commands",
        value=custom_commands,
        inline=False
    )

    custom_embed.add_field(
        name="Notes",
        value=(
            "• Custom answers (using `.cah c`) are marked with ✏️\n"
            "• Custom cards (using `.cah save`) need moderator approval\n"
            "• Approved cards are added to the permanent deck"
        ),
        inline=False
    )

    # Create buttons for quick actions
    view = View(timeout=None)

    # Start Game button
    start_button = Button(style=ButtonStyle.green, label="Start Game", custom_id="start_game")
    async def start_callback(interaction):
        # Check if user is in a voice channel
        if not interaction.user.voice:
            await interaction.response.send_message("You need to be in a voice channel to start a game!", ephemeral=True)
            return
        # Create proper context and start game
        ctx = await bot.get_context(interaction.message, cls=commands.Context)
        ctx.author = interaction.user  # Set correct author for voice channel check
        await start_game(ctx)
    start_button.callback = start_callback

    # Join Game button
    join_button = Button(style=ButtonStyle.blurple, label="Join Game", custom_id="join_game")
    async def join_callback(interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("You need to be in a voice channel to join the game!", ephemeral=True)
            return

        # Create proper context and join game
        ctx = await bot.get_context(interaction.message, cls=commands.Context)
        ctx.author = interaction.user  # Set correct author for voice channel check
        await join_game(ctx)
    join_button.callback = join_callback

    # Custom Card button
    custom_button = Button(style=ButtonStyle.gray, label="Create Custom Card", custom_id="create_custom")
    async def custom_callback(interaction):
        await save_custom_answer(await bot.get_context(interaction.message, cls=commands.Context))
    custom_button.callback = custom_callback

    view.add_item(start_button)
    view.add_item(join_button)
    view.add_item(custom_button)

    # Send both embeds
    await ctx.send(embed=rules_embed)
    await ctx.send(embed=custom_embed, view=view)

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
            drawer_name = game.players[game.current_prompt_drawer]['name']
            prompt_embed = Embed(
                title="Wrong Player", 
                description=f"Only the current prompt drawer ({drawer_name}) can draw a black card!", 
                color=Color.red()
            )
            await ctx.send(embed=prompt_embed)
            return

    if not game:
        await ctx.send("No game is currently active!")
        return

    # Don't allow drawing a new card if a round is in progress
    if game.round_in_progress and game.current_black_card:
        embed = Embed(
            title="Round in Progress", 
            description=f"A round is already in progress!", 
            color=Color.red()
        )
        embed.add_field(name="Current Black Card", value=game.current_black_card['text'], inline=False)
        await ctx.send(embed=embed)
        return

    black_card = game.start_round()
    if black_card:
        logger.info(f"Drew black card: {black_card}")

        # Create an embed for the black card
        embed = Embed(
            title="🎲 New Round Started!", 
            description="A new black card has been drawn!", 
            color=Color.dark_grey()
        )
        
        # Make the black card stand out
        embed.add_field(
            name="📜 Black Card", 
            value=f"**{black_card}**", 
            inline=False
        )
        
        embed.add_field(
            name="👑 Prompt Drawer", 
            value=ctx.author.display_name, 
            inline=True
        )
        
        embed.add_field(
            name="⏭️ Next Step", 
            value="Other players must submit their white cards", 
            inline=True
        )
        
        embed.set_footer(text="White card answers will be sent via DM")

        # Send to the game channel if command was in DM
        if isinstance(ctx.channel, discord.DMChannel) and channel_id:
            try:
                game_channel = bot.get_channel(channel_id)
                if game_channel:
                    await game_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to send black card to game channel: {str(e)}")

        await ctx.send(embed=embed)

        # Notify all other players to play their cards
        for player_id in game.players:
            if player_id != game.current_prompt_drawer:
                try:
                    user = await bot.fetch_user(player_id)
                    
                    player_embed = Embed(
                        title="🎮 Your Turn to Play", 
                        description=f"A new black card has been drawn!", 
                        color=Color.dark_grey()
                    )
                    
                    player_embed.add_field(
                        name="📜 Black Card", 
                        value=f"**{black_card}**", 
                        inline=False
                    )
                    
                    player_embed.add_field(
                        name="Instructions", 
                        value="Use the buttons below your cards to play, or submit a custom answer!", 
                        inline=False
                    )
                    
                    # Create a view with draw cards button
                    player_view = View(timeout=None)
                    draw_button = Button(
                        style=ButtonStyle.green, 
                        label="Draw/View My Cards", 
                        emoji="🃏", 
                        custom_id="view_my_cards"
                    )
                    
                    custom_button = Button(
                        style=ButtonStyle.blurple, 
                        label="Submit Custom Answer", 
                        emoji="✏️", 
                        custom_id="custom_answer_direct"
                    )
                    
                    async def view_cards_callback(interaction):
                        ctx = await bot.get_context(interaction.message, cls=commands.Context)
                        ctx.author = interaction.user
                        await draw_cards(ctx)
                    
                    async def custom_answer_callback(interaction):
                        custom_modal = discord.ui.Modal(title="Your Custom Answer")
                        custom_text = discord.ui.TextInput(
                            label="Your answer",
                            placeholder="Type your funny answer here...",
                            style=discord.TextStyle.paragraph
                        )
                        custom_modal.add_item(custom_text)

                        async def modal_callback(interaction):
                            try:
                                ctx = await bot.get_context(interaction.message, cls=commands.Context)
                                ctx.author = interaction.user
                                await play_custom_answer(ctx, answer=custom_text.value)
                                await interaction.response.send_message("Custom answer submitted!", ephemeral=True)
                            except Exception as e:
                                logger.error(f"Error in custom answer modal: {str(e)}")
                                await interaction.response.send_message("An error occurred. Please try typing `.cah c Your answer` instead.", ephemeral=True)

                        custom_modal.on_submit = modal_callback
                        await interaction.response.send_modal(custom_modal)
                    
                    draw_button.callback = view_cards_callback
                    custom_button.callback = custom_answer_callback
                    
                    player_view.add_item(draw_button)
                    player_view.add_item(custom_button)
                    
                    await user.send(embed=player_embed, view=player_view)
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
async def save_custom_answer(ctx, card_type: str = None, *, card_text: str = None):
    """Save a custom answer to be used in future games"""
    # If no arguments provided, show an interactive modal
    if card_type is None or card_text is None:
        # Create a modal for custom card submission
        async def send_card_modal(interaction, card_type):
            modal = discord.ui.Modal(title=f"Create Custom {card_type.capitalize()} Card")
            card_input = discord.ui.TextInput(
                label=f"Your custom {card_type} card text",
                placeholder="Enter your card text here...",
                style=discord.TextStyle.paragraph,
                max_length=200
            )
            modal.add_item(card_input)

            async def modal_submit(interaction):
                # Process the submitted card
                game = game_manager.get_game(ctx.channel.id)
                if not game:
                    # Create temporary game for database access
                    game_manager.create_game(ctx.channel.id)
                    game = game_manager.get_game(ctx.channel.id)

                if game.add_custom_card(card_input.value, card_type.lower(), interaction.user.id):
                    embed = Embed(
                        title="✅ Card Saved", 
                        description=f"Your custom {card_type} card has been saved!", 
                        color=Color.green()
                    )
                    embed.add_field(name="Card Text", value=card_input.value, inline=False)
                    embed.add_field(name="Status", value="Awaiting moderator approval", inline=False)
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(
                        "Failed to save card. It might already exist.", 
                        ephemeral=True
                    )

            modal.on_submit = modal_submit
            await interaction.response.send_modal(modal)

        # Create card type selection buttons
        embed = Embed(
            title="Create Custom Card", 
            description="Select the type of card you want to create:", 
            color=Color.blue()
        )

        view = View(timeout=None)
        white_button = Button(style=ButtonStyle.secondary, label="White Card (Answer)", custom_id="white_card")
        black_button = Button(style=ButtonStyle.primary, label="Black Card (Prompt)", custom_id="black_card")

        async def white_callback(interaction):
            await send_card_modal(interaction, "white")

        async def black_callback(interaction):
            await send_card_modal(interaction, "black")

        white_button.callback = white_callback
        black_button.callback = black_callback

        view.add_item(white_button)
        view.add_item(black_button)

        await ctx.send(embed=embed, view=view)
        return

    # Process command with provided arguments
    if card_type.lower() not in ['white', 'black']:
        await ctx.send("Please specify either 'white' or 'black' as the card type!")
        return

    game = game_manager.get_game(ctx.channel.id)
    if not game:
        # Create temporary game for database access
        game_manager.create_game(ctx.channel.id)
        game = game_manager.get_game(ctx.channel.id)

    if game.add_custom_card(card_text, card_type.lower(), ctx.author.id):
        embed = Embed(
            title="✅ Card Saved", 
            description=f"Your custom {card_type} card has been saved!", 
            color=Color.green()
        )
        embed.add_field(name="Card Text", value=card_text, inline=False)
        embed.add_field(name="Status", value="Awaiting moderator approval", inline=False)
        await ctx.send(embed=embed)
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