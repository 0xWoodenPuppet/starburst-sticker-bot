"""Generate a clean, minimalistic leaderboard image for the 21-day challenge."""

import csv
from collections import defaultdict
from PIL import Image, ImageDraw, ImageFont

# --- Data ---
user_days = defaultdict(dict)
usernames = {}

with open("challenge_scores.csv", "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        uid = row["user_id"]
        username = row["username"]
        points = int(row["points"])
        day = int(row["day_number"])
        usernames[uid] = username
        if day not in user_days[uid] or points > user_days[uid][day]:
            user_days[uid][day] = points

leaderboard = []
for uid, days in user_days.items():
    total = sum(days.values())
    unique_days = len(days)
    leaderboard.append((usernames[uid], total, unique_days))

leaderboard.sort(key=lambda x: x[1], reverse=True)

# --- Design ---
BG_COLOR = (18, 18, 24)
TEXT_COLOR = (220, 220, 230)
SUBTEXT_COLOR = (130, 130, 150)
ACCENT_COLOR = (140, 155, 255)
DIVIDER_COLOR = (40, 40, 55)
ALT_ROW = (25, 25, 35)

# Fonts - Arial Unicode for Arabic support
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

font_title = ImageFont.truetype(FONT_BOLD, 26)
font_header = ImageFont.truetype(FONT_PATH, 14)
font_row = ImageFont.truetype(FONT_PATH, 15)
font_footer = ImageFont.truetype(FONT_PATH, 12)

# Layout
padding_x = 40
padding_top = 40
row_height = 32
title_height = 50
header_height = 32
footer_height = 45
num_players = len(leaderboard)

img_width = 520
img_height = padding_top + title_height + header_height + (num_players * row_height) + footer_height + 15

# --- Draw ---
img = Image.new("RGB", (img_width, img_height), BG_COLOR)
draw = ImageDraw.Draw(img)

# Title
title_text = "21-Day Study Challenge"
title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
title_w = title_bbox[2] - title_bbox[0]
draw.text(((img_width - title_w) / 2, padding_top), title_text, fill=ACCENT_COLOR, font=font_title)

y = padding_top + title_height

# Column positions
col_rank = padding_x
col_name = padding_x + 36
col_pts = img_width - padding_x - 115
col_days = img_width - padding_x - 40

# Header
draw.text((col_rank, y), "#", fill=SUBTEXT_COLOR, font=font_header)
draw.text((col_name, y), "Player", fill=SUBTEXT_COLOR, font=font_header)
draw.text((col_pts, y), "Points", fill=SUBTEXT_COLOR, font=font_header)
draw.text((col_days, y), "Days", fill=SUBTEXT_COLOR, font=font_header)

y += header_height
draw.line([(padding_x, y - 6), (img_width - padding_x, y - 6)], fill=DIVIDER_COLOR, width=1)

# Rows
for i, (name, total, days) in enumerate(leaderboard, 1):
    rank_str = str(i)
    pts_str = str(total)
    days_str = str(days)

    if i % 2 == 0:
        draw.rectangle(
            [(padding_x - 10, y - 2), (img_width - padding_x + 10, y + row_height - 4)],
            fill=ALT_ROW,
        )

    draw.text((col_rank, y), rank_str, fill=SUBTEXT_COLOR, font=font_row)
    draw.text((col_name, y), name, fill=TEXT_COLOR, font=font_row)

    # Right-align points
    pts_bbox = draw.textbbox((0, 0), pts_str, font=font_row)
    pts_w = pts_bbox[2] - pts_bbox[0]
    draw.text((col_pts + 38 - pts_w, y), pts_str, fill=TEXT_COLOR, font=font_row)

    # Right-align days
    days_bbox = draw.textbbox((0, 0), days_str, font=font_row)
    days_w = days_bbox[2] - days_bbox[0]
    draw.text((col_days + 18 - days_w, y), days_str, fill=SUBTEXT_COLOR, font=font_row)

    y += row_height

# Bottom divider
draw.line([(padding_x, y + 2), (img_width - padding_x, y + 2)], fill=DIVIDER_COLOR, width=1)

# Footer
y += 15
footer = f"{num_players} participants  ·  max 588 pts"
footer_bbox = draw.textbbox((0, 0), footer, font=font_footer)
footer_w = footer_bbox[2] - footer_bbox[0]
draw.text(((img_width - footer_w) / 2, y), footer, fill=SUBTEXT_COLOR, font=font_footer)

# Save
out_path = "leaderboard.png"
img.save(out_path, "PNG")
print(f"Saved to {out_path} ({img_width}x{img_height})")
