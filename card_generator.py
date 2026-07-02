import os
import io
import urllib.request
from PIL import Image, ImageDraw, ImageFont
from config import VC_XP_PER_MIN, TC_XP_REWARD

def check_font():
    font_dir = "assets/fonts"
    font_path = os.path.join(font_dir, "NotoSansJP[wght].ttf")
    if not os.path.exists(font_path):
        os.makedirs(font_dir, exist_ok=True)
        print("Downloading font Noto Sans JP...")
        url = "https://raw.githubusercontent.com/google/fonts/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf"
        urllib.request.urlretrieve(url, font_path)
        print("Font downloaded.")
    return font_path

def crop_max_square(image):
    w, h = image.size
    min_size = min(w, h)
    return image.crop(((w - min_size) // 2, (h - min_size) // 2, (w + min_size) // 2, (h + min_size) // 2))

def make_circle(image_bytes, size, border_color=(190, 46, 221), border_width=4):
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception as e:
        print(f"[card_generator] Failed to open image: {e}")
        img = Image.new("RGBA", (size, size), (255, 255, 255, 30))
    
    img = crop_max_square(img).resize((size, size), Image.Resampling.LANCZOS)
    
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size, size), fill=255)
    
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(img, (0, 0), mask=mask)
    
    if border_width > 0:
        draw = ImageDraw.Draw(output)
        draw.ellipse(
            (border_width//2, border_width//2, size - border_width//2 - 1, size - border_width//2 - 1),
            outline=border_color,
            width=border_width
        )
        
    return output

def draw_badge(draw, x, y, text, font, bg_color=(190, 46, 221, 60), text_color=(255, 255, 255, 255)):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    
    padding_x = 14
    padding_y = 6
    badge_w = tw + padding_x * 2
    badge_h = th + padding_y * 2
    
    draw.rounded_rectangle(
        [(x, y), (x + badge_w, y + badge_h)],
        radius=badge_h // 2,
        fill=bg_color
    )
    
    draw.text((x + padding_x - bbox[0], y + padding_y - bbox[1] - 2), text, font=font, fill=text_color, stroke_width=1, stroke_fill=text_color)
    return badge_w

def draw_progress_bar(base_img, x, y, w, h, current, total, bar_type="vc"):
    draw = ImageDraw.Draw(base_img)
    
    # 背景バーを描画
    draw.rounded_rectangle(
        [(x, y), (x + w, y + h)],
        radius=h // 2,
        fill=(15, 15, 25, 220)
    )
    
    if total <= 0:
        total = 100
    pct = min(current / total, 1.0)
    if pct <= 0:
        return
        
    fill_w = int(w * pct)
    if fill_w < h:
        fill_w = h
        
    bar_img = Image.new("RGBA", (fill_w, h), (0, 0, 0, 0))
    bar_draw = ImageDraw.Draw(bar_img)
    
    if bar_type == "vc":
        start_color = (190, 46, 221)
        end_color = (224, 86, 253)
    else:
        start_color = (9, 132, 227)
        end_color = (0, 206, 201)
        
    for px in range(fill_w):
        factor = px / fill_w
        r = int(start_color[0] + (end_color[0] - start_color[0]) * factor)
        g = int(start_color[1] + (end_color[1] - start_color[1]) * factor)
        b = int(start_color[2] + (end_color[2] - start_color[2]) * factor)
        bar_draw.line([(px, 0), (px, h)], fill=(r, g, b, 255))
        
    mask = Image.new("L", (fill_w, h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (fill_w, h)], radius=h // 2, fill=255)
    
    grad_bar = Image.new("RGBA", (fill_w, h), (0, 0, 0, 0))
    grad_bar.paste(bar_img, (0, 0), mask=mask)
    
    base_img.paste(grad_bar, (x, y), mask=grad_bar)

async def generate_rank_card(
    user_name: str,
    avatar_bytes: bytes,
    server_logo_bytes: bytes,
    vc_level: int,
    vc_xp: int,
    vc_next_xp: int,
    vc_role_name: str,
    tc_level: int = 1,
    tc_xp: int = 0,
    tc_next_xp: int = 100,
    tc_role_name: str = None,
    enable_tc: bool = True,
    eval_time_str: str = "0時間0分0秒"
) -> bytes:
    font_path = check_font()
    
    bg_path = "assets/background.png"
    if os.path.exists(bg_path):
        base = Image.open(bg_path).convert("RGBA")
    else:
        base = Image.new("RGBA", (900, 450), (15, 10, 25, 255))
        
    if base.size != (900, 450):
        base = base.resize((900, 450), Image.Resampling.LANCZOS)
        
    draw = ImageDraw.Draw(base)
    
    # フォントの準備
    font_name = ImageFont.truetype(font_path, 38)
    font_label = ImageFont.truetype(font_path, 22)
    font_value = ImageFont.truetype(font_path, 26)
    font_badge = ImageFont.truetype(font_path, 16)
    font_xp = ImageFont.truetype(font_path, 18)
    font_footer = ImageFont.truetype(font_path, 20)
    
    white = (255, 255, 255, 255)
    light_gray = (220, 220, 240, 255)
    
    # 外枠
    draw.rounded_rectangle(
        [(25, 25), (875, 425)],
        radius=20,
        outline=(190, 46, 221, 80),
        width=2
    )
    
    # 文字が見やすくなるよう、テキスト描画領域の背景に半透明の暗いマスクを敷く
    # サイズをアバターやロゴまで広げ、透明度を40%（不透明度102/255）に調整
    draw.rounded_rectangle(
        [(40, 45), (860, 405)],
        radius=15,
        fill=(10, 10, 20, 102)  # 半透明の暗い黒（不透明度102 = 40%）
    )
    
    # アバターの描画
    avatar_size = 140
    avatar_img = make_circle(avatar_bytes, avatar_size, border_color=(190, 46, 221, 255), border_width=4)
    base.paste(avatar_img, (50, 60), mask=avatar_img)
    
    # サーバーロゴの描画
    if server_logo_bytes:
        logo_size = 80
        logo_img = make_circle(server_logo_bytes, logo_size, border_color=(190, 46, 221, 150), border_width=3)
        base.paste(logo_img, (760, 50), mask=logo_img)
        
    # ユーザー名の描画
    draw.text((215, 55), user_name, font=font_name, fill=white, stroke_width=1, stroke_fill=white)
    
    if enable_tc:
        # --- VCレイアウト (上段) ---
        draw.text((215, 120), "VC Level:", font=font_label, fill=light_gray, stroke_width=1, stroke_fill=light_gray)
        lv_text = f"Lv.{vc_level}"
        draw.text((325, 116), lv_text, font=font_value, fill=white, stroke_width=1, stroke_fill=white)
        
        if vc_role_name:
            draw_badge(draw, 415, 116, vc_role_name, font_badge, bg_color=(190, 46, 221, 80))
            
        vc_needed = vc_next_xp - vc_xp
        vc_est_mins = -(-vc_needed // VC_XP_PER_MIN)
        xp_text = f"VC XP {vc_xp}/{vc_next_xp}  (次のレベルまであと {vc_needed} XP / 目安: 約{vc_est_mins}分の滞在)"
        draw.text((215, 155), xp_text, font=font_xp, fill=light_gray, stroke_width=1, stroke_fill=light_gray)
        draw_progress_bar(base, 215, 185, 620, 18, vc_xp, vc_next_xp, bar_type="vc")
        
        # --- TCレイアウト (下段) ---
        draw.text((215, 230), "TC Level:", font=font_label, fill=light_gray, stroke_width=1, stroke_fill=light_gray)
        tc_lv_text = f"Lv.{tc_level}"
        draw.text((325, 226), tc_lv_text, font=font_value, fill=white, stroke_width=1, stroke_fill=white)
        
        if tc_role_name:
            draw_badge(draw, 415, 226, tc_role_name, font_badge, bg_color=(9, 132, 227, 100))
            
        tc_needed = tc_next_xp - tc_xp
        tc_est_msgs = -(-tc_needed // TC_XP_REWARD)
        tc_xp_text = f"TC XP {tc_xp}/{tc_next_xp}  (次のレベルまであと {tc_needed} XP / 目安: 約{tc_est_msgs}通のチャット)"
        draw.text((215, 265), tc_xp_text, font=font_xp, fill=light_gray, stroke_width=1, stroke_fill=light_gray)
        draw_progress_bar(base, 215, 295, 620, 18, tc_xp, tc_next_xp, bar_type="tc")
        
        # --- 下部情報 (評価浮上時間) ---
        footer_text = f"評価浮上時間: {eval_time_str}"
        draw.text((215, 355), footer_text, font=font_footer, fill=white, stroke_width=1, stroke_fill=white)
        
    else:
        # --- VCのみのレイアウト (中央配置) ---
        draw.text((215, 120), "VC Level:", font=font_label, fill=light_gray, stroke_width=1, stroke_fill=light_gray)
        lv_text = f"Lv.{vc_level}"
        draw.text((325, 116), lv_text, font=font_value, fill=white, stroke_width=1, stroke_fill=white)
        
        if vc_role_name:
            draw_badge(draw, 415, 116, vc_role_name, font_badge, bg_color=(190, 46, 221, 80))
            
        vc_needed = vc_next_xp - vc_xp
        vc_est_mins = -(-vc_needed // VC_XP_PER_MIN)
        xp_text = f"VC XP {vc_xp}/{vc_next_xp}  (次のレベルまであと {vc_needed} XP)"
        draw.text((215, 160), xp_text, font=font_xp, fill=light_gray, stroke_width=1, stroke_fill=light_gray)
        
        est_text = f"┗ レベルアップの目安: あと約 {vc_est_mins} 分の滞在"
        draw.text((215, 190), est_text, font=font_xp, fill=light_gray, stroke_width=1, stroke_fill=light_gray)
        
        draw_progress_bar(base, 215, 230, 620, 24, vc_xp, vc_next_xp, bar_type="vc")
        
        # --- 下部情報 (評価浮上時間) ---
        footer_text = f"評価浮上時間: {eval_time_str}"
        draw.text((215, 310), footer_text, font=font_footer, fill=white, stroke_width=1, stroke_fill=white)
        
    output_bytes = io.BytesIO()
    base.save(output_bytes, format="PNG")
    return output_bytes.getvalue()
