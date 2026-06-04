"""Generate a clean, minimalistic two-column leaderboard image.
Uses the same ranking logic as the /leaderboard bot command:
- Sum ALL points per user (no deduplication by day)
- Dense ranking (tied totals = same rank)
- Tiebreaker: user 5534874386 (Ariadayvi) is prioritised
"""

import csv
import re
from collections import defaultdict
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

# --- Data (mirrors scoring.py logic) ---
PRIORITY_UID = "5534874386"

totals = {}
with open("challenge_scores.csv", "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        uid = row["user_id"]
        points = int(row["points"])
        if uid not in totals:
            totals[uid] = {"uid": uid, "username": row["username"], "total": 0, "days": set()}
        totals[uid]["total"] += points
        totals[uid]["days"].add(int(row["day_number"]))
        totals[uid]["username"] = row["username"]  # keep latest

# Sort: descending total, tiebreaker for priority uid
sorted_users = sorted(
    totals.values(),
    key=lambda x: (-x["total"], 0 if x["uid"] == PRIORITY_UID else 1),
)

# Dense ranking
def dense_ranks(sorted_users):
    ranks = []
    current_rank = 0
    prev_total = None
    for user in sorted_users:
        if user["total"] != prev_total:
            current_rank += 1
            prev_total = user["total"]
        ranks.append((current_rank, user))
    return ranks

ranked = dense_ranks(sorted_users)
leaderboard = [(rank, u["username"], u["total"], len(u["days"])) for rank, u in ranked]


def has_arabic(text):
    return bool(re.search(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]', text))


def render_name(text):
    if has_arabic(text):
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    return text


# --- Design ---
BG_COLOR = (15, 15, 22)
TEXT_COLOR = (210, 212, 225)
SUBTEXT_COLOR = (110, 115, 135)
ACCENT_COLOR = (130, 145, 255)
DIVIDER_COLOR = (35, 38, 50)
ALT_ROW = (22, 22, 32)

# Fonts
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

font_title = ImageFont.truetype(FONT_BOLD, 24)
font_subtitle = ImageFont.truetype(FONT_PATH, 12)
font_header = ImageFont.truetype(FONT_PATH, 12)
font_row = ImageFont.truetype(FONT_PATH, 14)
font_footer = ImageFont.truetype(FONT_PATH, 11)

# Layout
row_height = 30
title_area = 70
header_height = 28
footer_height = 40
padding_x = 30
padding_y = 30
col_gap = 25

mid = (len(leaderboard) + 1) // 2  # 18 left, 18 right
left_col = leaderboard[:mid]
right_col = leaderboard[mid:]
max_rows = max(len(left_col), len(right_col))

col_width = 340
img_width = padding_x + col_width + col_gap + col_width + padding_x
img_height = padding_y + title_area + header_height + (max_rows * row_height) + footer_height + 10

# --- Draw ---
img = Image.new("RGB", (img_width, img_height), BG_COLOR)
draw = ImageDraw.Draw(img)

# Title
title_text = "21-Day Study Challenge"
title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
title_w = title_bbox[2] - title_bbox[0]
draw.text(((img_width - title_w) / 2, padding_y), title_text, fill=ACCENT_COLOR, font=font_title)

# Subtitle
sub_text = "Final Leaderboard"
sub_bbox = draw.textbbox((0, 0), sub_text, font=font_subtitle)
sub_w = sub_bbox[2] - sub_bbox[0]
draw.text(((img_width - sub_w) / 2, padding_y + 32), sub_text, fill=SUBTEXT_COLOR, font=font_subtitle)

y_start = padding_y + title_area


def draw_column(entries, x_offset, y_top):
    """Draw one column of the leaderboard."""
    cx_rank = x_offset
    cx_name = x_offset + 30
    cx_pts = x_offset + col_width - 68
    cx_days = x_offset + col_width - 15

    # Header
    draw.text((cx_rank, y_top), "#", fill=SUBTEXT_COLOR, font=font_header)
    draw.text((cx_name, y_top), "Player", fill=SUBTEXT_COLOR, font=font_header)
    draw.text((cx_pts, y_top), "Pts", fill=SUBTEXT_COLOR, font=font_header)
    draw.text((cx_days - 10, y_top), "Days", fill=SUBTEXT_COLOR, font=font_header)

    y = y_top + header_height
    draw.line([(x_offset, y - 6), (x_offset + col_width, y - 6)], fill=DIVIDER_COLOR, width=1)

    for idx, (rank, name, total, days) in enumerate(entries):
        rank_str = str(rank)
        pts_str = str(total)
        days_str = str(days)
        display_name = render_name(name)

        # Alternate row bg based on position in list
        if idx % 2 == 1:
            draw.rectangle(
                [(x_offset - 5, y - 1), (x_offset + col_width + 5, y + row_height - 3)],
                fill=ALT_ROW,
            )

        # Rank (right-aligned)
        rank_bbox = draw.textbbox((0, 0), rank_str, font=font_row)
        rank_w = rank_bbox[2] - rank_bbox[0]
        draw.text((cx_rank + 18 - rank_w, y), rank_str, fill=SUBTEXT_COLOR, font=font_row)

        # Name
        draw.text((cx_name, y), display_name, fill=TEXT_COLOR, font=font_row)

        # Points (right-aligned)
        pts_bbox = draw.textbbox((0, 0), pts_str, font=font_row)
        pts_w = pts_bbox[2] - pts_bbox[0]
        draw.text((cx_pts + 25 - pts_w, y), pts_str, fill=TEXT_COLOR, font=font_row)

        # Days (right-aligned)
        days_bbox = draw.textbbox((0, 0), days_str, font=font_row)
        days_w = days_bbox[2] - days_bbox[0]
        draw.text((cx_days - days_w, y), days_str, fill=SUBTEXT_COLOR, font=font_row)

        y += row_height

    # Bottom line
    draw.line([(x_offset, y + 2), (x_offset + col_width, y + 2)], fill=DIVIDER_COLOR, width=1)


# Draw columns
draw_column(left_col, padding_x, y_start)
draw_column(right_col, padding_x + col_width + col_gap, y_start)

# Vertical divider
div_x = padding_x + col_width + col_gap // 2
draw.line(
    [(div_x, y_start + header_height - 6), (div_x, y_start + header_height + max_rows * row_height + 2)],
    fill=DIVIDER_COLOR,
    width=1,
)

# Footer
fy = y_start + header_height + max_rows * row_height + 18
footer = f"{len(leaderboard)} participants  ·  dense ranking"
footer_bbox = draw.textbbox((0, 0), footer, font=font_footer)
footer_w = footer_bbox[2] - footer_bbox[0]
draw.text(((img_width - footer_w) / 2, fy), footer, fill=SUBTEXT_COLOR, font=font_footer)

# Save
out_path = "leaderboard.png"
img.save(out_path, "PNG")
print(f"Saved to {out_path} ({img_width}x{img_height})")

# Print for verification
for rank, name, total, days in leaderboard:
    print(f"  Rank {rank}: @{name} — {total} pts ({days} days)")
