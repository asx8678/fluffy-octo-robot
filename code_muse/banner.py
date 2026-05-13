"""Beautiful ASCII art banner for Muse launch.

Provides a baked-in banner that works without pyfiglet,
with Rich-powered gradient coloring.
"""

# The "big" figlet font for "MUSE" — embedded so no dependency needed
BANNER_LINES = [
    r" __  __ _    _  _____ ______ ",
    r"|  \/  | |  | |/ ____|  ____|",
    r"| \  / | |  | | (___ | |__   ",
    r"| |\/| | |  | |\___ \|  __|  ",
    r"| |  | | |__| |____) | |____ ",
    r"|_|  |_|\____/|_____/|______|",
]

# Tagline shown below the logo
TAGLINE = "✦  elevate your code  ✦"


def render_banner(console) -> None:
    """Render the Muse banner with a warm gradient effect.

    Colors flow from gold → orange → magenta (top to bottom),
    giving a sunrise-to-sunset feel.
    """
    from rich.text import Text

    # ── gradient palette ────────────────────────────────────────────
    # Each line gets a progressively warmer / deeper colour
    palette = [
        "bright_yellow",
        "gold1",
        "dark_orange",
        "orange_red1",
        "bright_red",
        "medium_purple1",
    ]

    text = Text()
    text.append("\n")

    for i, line in enumerate(BANNER_LINES):
        colour = palette[i] if i < len(palette) else palette[-1]
        # Bold makes the block chars pop
        text.append(line, style=f"bold {colour}")
        text.append("\n")

    # ── tagline ─────────────────────────────────────────────────────
    text.append("\n")
    text.append(f"     {TAGLINE}", style="italic bright_cyan")
    text.append("\n\n")

    console.print(text)
