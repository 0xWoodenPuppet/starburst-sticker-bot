import re

texts = [
    "I'm planting a 25-minute tree in Forest. Join my room: ABCDEF12 https://...",
    "Estoy plantando un árbol de 25-minutos en Forest. Únete: ABCDEF12",
    "Je plante un arbre de 25 minutes dans Forest. Rejoignez: ABCDEF12",
    "我在 Forest 種植了一棵 25 分鐘的樹。加入房間：ABCDEF12",
    "أزرع شجرة لمدة ٢٥ دقيقة في Forest. انضم إلى غرفتي: ABCDEF12",
    "I'm planting a 2-tier Cake for 25 minutes..."
]

for t in texts:
    match = re.search(r"(\d+)", t)
    if match:
        print(f"Text: {t[:30]}... -> Number: {match.group(1)} (Value: {int(match.group(1))})")
