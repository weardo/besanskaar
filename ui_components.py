"""UI components for Cards Against Humanity Discord bot"""
import discord
from discord.ui import Button, View, Select
from typing import List, Dict
import logging

# Import GameManager singleton
from game import GameManager

logger = logging.getLogger(__name__)

class GameStartView(View):
    def __init__(self, channel_id: int, timeout=180):
        super().__init__(timeout=timeout)
        self.channel_id = int(channel_id)  # Ensure channel_id is int
        self.add_item(JoinGameButton(self.channel_id))
        logger.debug(f"GameStartView created for channel {self.channel_id}")

class JoinGameButton(Button):
    def __init__(self, channel_id: int):
        super().__init__(
            style=discord.ButtonStyle.green,
            label="Join Game",
            emoji="🎮"
        )
        self.channel_id = int(channel_id)  # Ensure channel_id is int

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("You need to be in a voice channel to join!", ephemeral=True)
            return

        # Get the singleton instance
        game_manager = GameManager.get_instance()

        # Debug logging
        logger.debug(f"GameManager instance ID: {id(game_manager)}")
        logger.debug(f"Checking game in channel {self.channel_id} (type: {type(self.channel_id)})")
        logger.debug(f"Active games: {list(game_manager.games.keys())}")

        game = game_manager.get_game(self.channel_id)
        if not game:
            logger.error(f"No game found for channel {self.channel_id}")
            await interaction.response.send_message("No active game in this channel!", ephemeral=True)
            return

        success = await game_manager.add_player(self.channel_id, interaction.user.id, interaction.user.name, interaction.user)
        if success:
            # Create welcome embed
            embed = discord.Embed(
                title="Welcome to Cards Against Humanity!",
                description="You've joined the game! I'll manage your cards here.\nClick the button below to draw your cards.",
                color=discord.Color.green()
            )

            # Add draw cards button
            view = View(timeout=None)
            view.add_item(DrawCardsButton(self.channel_id))

            try:
                await interaction.user.send(embed=embed, view=view)
                await interaction.response.send_message("You've joined the game! Check your DMs.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message(
                    "I couldn't send you a DM. Please enable DMs from server members to play!",
                    ephemeral=True
                )
        else:
            await interaction.response.send_message("You're already in the game!", ephemeral=True)

class DrawCardsButton(Button):
    def __init__(self, channel_id: int):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="Draw Cards",
            emoji="🃏"
        )
        self.channel_id = int(channel_id) #Ensure channel_id is int

    async def callback(self, interaction: discord.Interaction):
        game_manager = GameManager.get_instance()
        game = game_manager.get_game(self.channel_id)
        if not game:
            await interaction.response.send_message("No active game found!", ephemeral=True)
            return

        cards = game.draw_cards(interaction.user.id)
        if cards:
            # Create card selection view
            embed = discord.Embed(
                title="Your Cards",
                description="Select a card to play when it's your turn!",
                color=discord.Color.blue()
            )

            view = CardSelectView(self.channel_id, cards)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message("You already have cards or aren't in the game!", ephemeral=True)

class CardSelectView(View):
    def __init__(self, channel_id: int, cards: List[str], timeout=None):
        super().__init__(timeout=timeout)
        self.channel_id = int(channel_id) #Ensure channel_id is int
        self.add_item(CardSelectMenu(self.channel_id, cards))

class CardSelectMenu(Select):
    def __init__(self, channel_id: int, cards: List[str]):
        self.channel_id = int(channel_id) #Ensure channel_id is int
        options = [
            discord.SelectOption(
                label=f"Card {i+1}",
                description=card[:100],  # Discord has a 100-char limit for descriptions
                value=str(i)
            )
            for i, card in enumerate(cards)
        ]
        super().__init__(
            placeholder="Choose a card to play...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        game_manager = GameManager.get_instance()
        game = game_manager.get_game(self.channel_id)
        if not game:
            await interaction.response.send_message("No active game found!", ephemeral=True)
            return

        card_index = int(self.values[0])
        success = await game.handle_played_card(interaction.user.id, card_index)
        if success:
            embed = discord.Embed(
                title="Card Played!",
                description="Your card has been played. Wait for other players...",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(
                "Couldn't play that card. Either it's not your turn or you're the prompt drawer.",
                ephemeral=True
            )

class WinnerSelectView(View):
    def __init__(self, channel_id: int, played_cards: Dict[str, Dict[str, str]], timeout=None):
        super().__init__(timeout=timeout)
        self.channel_id = int(channel_id) #Ensure channel_id is int
        self.add_item(WinnerSelectMenu(self.channel_id, played_cards))

class WinnerSelectMenu(Select):
    def __init__(self, channel_id: int, played_cards: Dict[str, Dict[str, str]]):
        self.channel_id = int(channel_id) #Ensure channel_id is int
        options = [
            discord.SelectOption(
                label=f"Card {i+1}",
                description=card_info['card'][:100],
                value=str(player_id)
            )
            for i, (player_id, card_info) in enumerate(played_cards.items())
        ]
        super().__init__(
            placeholder="Choose the winning card...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        game_manager = GameManager.get_instance()
        game = game_manager.get_game(self.channel_id)
        if not game:
            await interaction.response.send_message("No active game found!", ephemeral=True)
            return

        if interaction.user.id != game.current_prompt_drawer:
            await interaction.response.send_message("Only the prompt drawer can select the winner!", ephemeral=True)
            return

        winning_player_id = int(self.values[0])
        if game.select_winner(winning_player_id):
            # Show winner in main channel
            winning_card = game.get_played_cards()[winning_player_id]
            channel = interaction.client.get_channel(self.channel_id)
            await channel.send(
                f"🎉 **Winner**: {winning_card['player_name']} with \"{winning_card['card']}\"!"
            )

            # Show scores
            scores = game.get_scores()
            scores_text = "\n".join([f"{info['name']}: {info['score']} points" for info in scores.values()])
            await channel.send(f"**Current Scores**:\n{scores_text}")

            # Announce next prompt drawer
            next_drawer = game.players[game.current_prompt_drawer]['name']
            await channel.send(f"\n👉 {next_drawer} will draw the next black card!")

            await interaction.response.send_message("Winner selected!", ephemeral=True)
        else:
            await interaction.response.send_message("Error selecting winner!", ephemeral=True)

async def send_winner_selection_dm(user, channel_id: int, played_cards):
    """Send winner selection interface to prompt drawer's DM"""
    embed = discord.Embed(
        title="Select Winning Card",
        description="Choose the winning card from the played cards below:",
        color=discord.Color.gold()
    )

    for i, (_, card_info) in enumerate(played_cards.items(), 1):
        embed.add_field(
            name=f"Card {i}",
            value=card_info['card'],
            inline=False
        )

    view = WinnerSelectView(channel_id, played_cards)
    try:
        await user.send(embed=embed, view=view)
        return True
    except discord.Forbidden:
        return False