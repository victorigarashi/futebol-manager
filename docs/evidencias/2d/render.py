"""Draw dumped engine frames like the 2D client (system python with PIL)."""
import sys, json, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
src, dst, label = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
dst.mkdir(parents=True, exist_ok=True)
SC, PAD = 7, 14
SUB = 4  # pictures per game second (the client interpolates between seconds)
def pitch(L, W):
    img = Image.new("RGB", (int(L * SC) + 2 * PAD, int(W * SC) + 2 * PAD + 26), (13, 17, 23))
    d = ImageDraw.Draw(img)
    for i in range(10):
        d.rectangle([PAD + i * L * SC / 10, PAD, PAD + (i + 1) * L * SC / 10, PAD + W * SC], fill=(29, 90, 44) if i % 2 else (26, 82, 40))
    w = (235, 245, 235)
    d.rectangle([PAD, PAD, PAD + L * SC, PAD + W * SC], outline=w, width=2)
    d.line([PAD + L * SC / 2, PAD, PAD + L * SC / 2, PAD + W * SC], fill=w, width=2)
    d.ellipse([PAD + L * SC / 2 - 9.15 * SC, PAD + W * SC / 2 - 9.15 * SC, PAD + L * SC / 2 + 9.15 * SC, PAD + W * SC / 2 + 9.15 * SC], outline=w, width=2)
    for x0, x1 in ((0, 16.5), (L - 16.5, L)):
        d.rectangle([PAD + x0 * SC, PAD + (W / 2 - 20.15) * SC, PAD + x1 * SC, PAD + (W / 2 + 20.15) * SC], outline=w, width=2)
    return img
def lerp(a, b, t): return a + (b - a) * t
for f in sorted(src.glob("*.json")):
    data = json.loads(f.read_text()); L, W, n0 = data["L"], data["W"], data["n_home"]
    frames = data["frames"]; base = pitch(L, W); pics = []
    shots = {e["tick"] for e in data["events"] if e["kind"] == "SHOT"}
    for a, b in zip(frames, frames[1:]):
        for k in range(SUB):
            t = k / SUB; img = base.copy(); d = ImageDraw.Draw(img)
            for i, (pa, pb) in enumerate(zip(a["p"], b["p"])):
                if pa is None or pb is None: continue
                x, y = lerp(pa[0], pb[0], t), lerp(pa[1], pb[1], t)
                if math.hypot(pb[0] - pa[0], pb[1] - pa[1]) > 0.14 * L:  # client: repositioned -> no slide
                    x, y = (pa if t < .5 else pb)
                col = (59, 130, 246) if i < n0 else (239, 68, 68)
                r = 1.4 * SC
                d.ellipse([PAD + x * SC - r, PAD + y * SC - r, PAD + x * SC + r, PAD + y * SC + r], fill=col, outline=(13, 17, 23), width=2)
                if b["b"][2] == i and b["b"][3] == 0:
                    d.ellipse([PAD + x * SC - r - 4, PAD + y * SC - r - 4, PAD + x * SC + r + 4, PAD + y * SC + r + 4], outline=(144, 252, 163), width=2)
            (bax, bay, _, sa), (bbx, bby, ob, sb) = a["b"], b["b"]
            bx, by, alpha = lerp(bax, bbx, t), lerp(bay, bby, t), 1.0
            if ob >= 0 and ob == a["b"][2] and b["p"][ob] and a["p"][ob]:
                bx, by = lerp(a["p"][ob][0], b["p"][ob][0], t), lerp(a["p"][ob][1], b["p"][ob][1], t)
            if sb != 3 and sa != 3 and (sa == 1 or sb == 1) and math.hypot((bbx - bax) / L, (bby - bay) / W) > 0.12:
                bx, by = (bax, bay) if t < .5 else (bbx, bby); alpha = abs(1 - 2 * t)  # old client: dead ball fades
            if alpha > .15:
                rb = 0.7 * SC
                d.ellipse([PAD + bx * SC - rb - 3, PAD + by * SC - rb - 3, PAD + bx * SC + rb + 3, PAD + by * SC + rb + 3], fill=(120, 140, 120))
                d.ellipse([PAD + bx * SC - rb, PAD + by * SC - rb, PAD + bx * SC + rb, PAD + by * SC + rb], fill=(255, 255, 255), outline=(13, 17, 23), width=2)
            minute = int(b["t"] // 60)
            d.text((PAD, PAD + W * SC + 6), f"{label} · {f.stem.upper()} · {minute}' · tick {b['t']}{'  ← CHUTE' if b['t'] in shots else ''}", fill=(241, 245, 249))
            pics.append(img)
    pics[0].save(dst / f"{f.stem}.gif", save_all=True, append_images=pics[1:], duration=90, loop=0)
    strip = Image.new("RGB", (pics[0].width * 3, pics[0].height * 2), (13, 17, 23))
    picks = [int(i * (len(pics) - 1) / 5) for i in range(6)]
    for n, p in enumerate(picks):
        strip.paste(pics[p], ((n % 3) * pics[0].width, (n // 3) * pics[0].height))
    strip.save(dst / f"{f.stem}_quadros.png")
print("ok", dst)
