#!/usr/bin/env python3
from pathlib import Path
import zipfile

chats = {
"chat_tile.txt": """05/01/26, 8:10 AM - Mia Carter: Hi, cracked tiles near shower. Wall feels soft and maybe water behind wall.
05/01/26, 8:11 AM - Mia Carter: Can you do before Friday? Budget is tight, need cheapest safe option.
05/01/26, 8:12 AM - Mia Carter: I don't know tile size or grout color yet.
05/01/26, 8:13 AM - You: Please share address and photos.
""",
"chat_toilet.txt": """05/01/26, 10:05 AM - Raj Patel: Need toilet replaced at 221 Cedar Ave.
05/01/26, 10:07 AM - Raj Patel: Model is Kohler K-3999 and I sent photos.
05/01/26, 10:08 AM - Raj Patel: Timing flexible, whenever next week.
""",
"chat_roof.txt": """05/02/26, 6:41 AM - Elena Ruiz: Emergency roof leak during rain, active leak and ceiling stain.
05/02/26, 6:42 AM - Elena Ruiz: Need help today asap. I don't have roof photos yet.
05/02/26, 6:43 AM - Elena Ruiz: Not sure where exactly on roof.
""",
"chat_electrical.txt": """05/02/26, 9:10 AM - Jordan Lee: Outlet is sparking in kitchen and breaker keeps tripping.
05/02/26, 9:11 AM - Jordan Lee: No power on that wall. urgent please.
05/02/26, 9:12 AM - Jordan Lee: Address is 45 Maple Street.
""",
"chat_reno.txt": """05/03/26, 11:20 AM - Alina Green: Looking for painting quote for living room at 12 North Road.
05/03/26, 11:45 AM - Alina Green: Also while you're here maybe flooring too.
05/03/26, 11:50 AM - Alina Green: maybe bathroom too, not sure sizes yet or materials.
""",
}

out = Path(__file__).parent / "demo_whatsapp_export.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for filename, chat_text in chats.items():
        zf.writestr(filename, chat_text)
    # tiny placeholder media files for multimodal smoke path
    zf.writestr("chat_tile_bathroom_tile_water_damage.jpg", b"not-a-real-image")
    zf.writestr("chat_roof_active_leak_video.mp4", b"not-a-real-video")
print(out)
