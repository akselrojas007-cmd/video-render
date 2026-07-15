import os, re, json, subprocess, textwrap, itertools, time
import urllib.parse
import requests

TEXT = os.environ["RENDER_TEXT"]
FPS = 25
MAX_SEG = 6.0  # segundos máximo por imagen

def run(cmd):
    subprocess.run(cmd, check=True)

def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())

# 1. Separar título e historia
title, story = TEXT.split("|||", 1)
title = title.strip()
story = story.strip()
with open("title.txt", "w") as f:
    f.write(title)

# 2. Separar en oraciones
sentences = re.split(r'(?<=[.!?]) +', story)
sentences = [s.strip() for s in sentences if s.strip()]

# 3. Generar audio por oración y trocear a máximo 6s por segmento
segments = []  # cada uno: {audio, duration, caption, sentence_idx}
seed = int(time.time()) % 100000

for idx, sentence in enumerate(sentences):
    raw_audio = f"raw_{idx}.mp3"
    run(["edge-tts", "--voice", "es-MX-DaliaNeural", "--text", sentence,
         "--write-media", raw_audio])
    dur = ffprobe_duration(raw_audio)

    n_pieces = max(1, int(dur // MAX_SEG) + (1 if dur % MAX_SEG > 0.3 else 0))
    piece_dur = dur / n_pieces

    for p in range(n_pieces):
        start = p * piece_dur
        seg_audio = f"seg_{idx}_{p}.mp3"
        run(["ffmpeg", "-y", "-i", raw_audio, "-ss", str(start), "-t", str(piece_dur),
             "-acodec", "libmp3lame", seg_audio])
        segments.append({
            "audio": seg_audio,
            "duration": piece_dur,
            "caption": sentence,
            "sentence_idx": idx,
        })

# 4. Generar UNA imagen por oración (todas las piezas de esa oración la comparten)
image_for_sentence = {}
for idx, sentence in enumerate(sentences):
    prompt = (
        "Ilustracion estilo cuento infantil, calida y emotiva, pintura digital "
        "suave, colores pastel, sin texto, mismo gatito protagonista en todas "
        f"las escenas. Escena: {sentence}"
    )
    encoded = urllib.parse.quote(prompt)
    img_path = f"scene_{idx}.jpg"
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&seed={seed}&model=flux&nologo=true"
    r = requests.get(url, timeout=60)
    with open(img_path, "wb") as f:
        f.write(r.content)
    image_for_sentence[idx] = img_path
    time.sleep(1.5)

# 5. Miniatura: primera imagen + título
from PIL import Image, ImageDraw, ImageFont

def make_thumbnail():
    img = Image.open(image_for_sentence[0]).convert("RGB")
    draw = ImageDraw.Draw(img)
    font_size = int(img.width / 10)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()
    wrapped = textwrap.fill(title, width=14)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center")
    text_w = bbox[2] - bbox[0]
    x = (img.width - text_w) / 2
    y = img.height * 0.68
    for dx in range(-4, 5, 2):
        for dy in range(-4, 5, 2):
            draw.multiline_text((x + dx, y + dy), wrapped, font=font, fill="black", align="center")
    draw.multiline_text((x, y), wrapped, font=font, fill="white", align="center")
    img.save("thumbnail.jpg", quality=92)

make_thumbnail()

# 6. Armar un clip por segmento: imagen + movimiento + subtítulo quemado + audio
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
movement_cycle = itertools.cycle(["zoom_in", "zoom_out", "pan_lr", "pan_rl"])

clip_files = []
for i, seg in enumerate(segments):
    move = next(movement_cycle)
    frames = max(1, int(seg["duration"] * FPS))
    img_path = image_for_sentence[seg["sentence_idx"]]

    if move == "zoom_in":
        zf = f"zoompan=z='min(zoom+0.0018,1.3)':d={frames}:s=1080x1920:fps={FPS}"
    elif move == "zoom_out":
        zf = f"zoompan=z='if(eq(on,1),1.3,max(zoom-0.0018,1.0))':d={frames}:s=1080x1920:fps={FPS}"
    elif move == "pan_lr":
        zf = (f"zoompan=z=1.18:d={frames}:s=1080x1920:fps={FPS}:"
              f"x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)'")
    else:  # pan_rl
        zf = (f"zoompan=z=1.18:d={frames}:s=1080x1920:fps={FPS}:"
              f"x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)'")

    caption_wrapped = textwrap.fill(seg["caption"], width=28).replace("'", "\u2019")
    caption_path = f"caption_{i}.txt"
    with open(caption_path, "w") as f:
        f.write(caption_wrapped)

    drawtext = (
        f"drawtext=fontfile={FONT}:textfile={caption_path}:fontsize=58:"
        "fontcolor=white:borderw=5:bordercolor=black:line_spacing=10:"
        "x=(w-text_w)/2:y=h*0.78"
    )

    clip_out = f"clip_{i}.mp4"
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", img_path,
        "-i", seg["audio"],
        "-filter_complex",
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,{zf}[z];[z]{drawtext}[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-c:a", "aac",
        "-shortest", "-t", str(seg["duration"]),
        clip_out,
    ])
    clip_files.append(clip_out)

# 7. Unir todos los clips
with open("concat_list.txt", "w") as f:
    for c in clip_files:
        f.write(f"file '{c}'\n")

run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat_list.txt", "-c", "copy", "video.mp4"])

print(f"Listo: {len(segments)} escenas generadas.")
