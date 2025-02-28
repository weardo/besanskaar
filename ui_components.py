"""UI components for Cards Against Humanity Discord bot"""
import discord
from discord.ui import Button, View, Select
from typing import List, Dict

class GameStartView(View):
    def __init__(self, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(JoinGameButton())

class JoinGameButton(Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.green,
            label="Join Game",
            emoji="🎮"
        )

    async def callback(self, interaction: discord.Interaction):
        from game import GameManager  # Import here to avoid circular imports

        if not interaction.user.voice:
            await interaction.response.send_message("You need to be in a voice channel to join!", ephemeral=True)
            return

        game_manager = GameManager()
        game = game_manager.get_game(interaction.channel_id)
        if not game:
            await interaction.response.send_message("No active game in this channel!", ephemeral=True)
            return

        success = game_manager.add_player(interaction.channel_id, interaction.user.id, interaction.user.name)
        if success:
            # Create welcome embed
            embed = discord.Embed(
                title="Welcome to Cards Against Humanity!",
                description="You've joined the game! I'll manage your cards here.\nClick the button below to draw your cards.",
                color=discord.Color.green()
            )

            # Add draw cards button
            view = View(timeout=None)
            view.add_item(DrawCardsButton())

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
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="Draw Cards",
            emoji="🃏"
        )

    async def callback(self, interaction: discord.Interaction):
        from game import GameManager

        game_manager = GameManager()
        game = game_manager.get_game(interaction.channel_id)
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

            view = CardSelectView(cards)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message("You already have cards or aren't in the game!", ephemeral=True)

class CardSelectView(View):
    def __init__(self, cards: List[str], timeout=None):
        super().__init__(timeout=timeout)
        self.add_item(CardSelectMenu(cards))

class CardSelectMenu(Select):
    def __init__(self, cards: List[str]):
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
        from game import GameManager

        game_manager = GameManager()
        game = game_manager.get_game(interaction.channel_id)
        if not game:
            await interaction.response.send_message("No active game found!", ephemeral=True)
            return

        card_index = int(self.values[0])
        success = game.play_card(interaction.user.id, card_index)
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
    def __init__(self, played_cards: Dict[str, Dict[str, str]], timeout=None):
        super().__init__(timeout=timeout)
        self.add_item(WinnerSelectMenu(played_cards))

class WinnerSelectMenu(Select):
    def __init__(self, played_cards: Dict[str, Dict[str, str]]):
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
        from game import GameManager

        game_manager = GameManager()
        game = game_manager.get_game(interaction.channel_id)
        if not game:
            await interaction.response.send_message("No active game found!", ephemeral=True)
            return

        if interaction.user.id != game.current_prompt_drawer:
            await interaction.response.send_message("Only the prompt drawer can select the winner!", ephemeral=True)
            return

        winning_player_id = self.values[0]
        if game.select_winner(winning_player_id):
            # Show winner in main channel
            winning_card = game.get_played_cards()[winning_player_id]
            await interaction.channel.send(
                f"🎉 **Winner**: {winning_card['player_name']} with \"{winning_card['card']}\"!"
            )

            # Show scores
            scores = game.get_scores()
            scores_text = "\n".join([f"{info['name']}: {info['score']} points" for info in scores.values()])
            await interaction.channel.send(f"**Current Scores**:\n{scores_text}")

            # Announce next prompt drawer
            next_drawer = game.players[game.current_prompt_drawer]['name']
            await interaction.channel.send(f"\n👉 {next_drawer} will draw the next black card!")

            await interaction.response.send_message("Winner selected!", ephemeral=True)
        else:
            await interaction.response.send_message("Error selecting winner!", ephemeral=True)