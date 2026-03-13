from flask import Flask, request, render_template, send_file
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
from io import BytesIO
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


def hex_to_rgb(hex_color):
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def process_single_image(input_image_bytes, bg_color=(255, 255, 255)):
    """Remove background locally with rembg, enhance, and return PIL image."""
    from rembg import remove

    print("DEBUG: Running local background removal with rembg...")

    # Step 1: Local background removal (no API, no credits)
    output_bytes = remove(input_image_bytes)
    img = Image.open(BytesIO(output_bytes))

    # Step 2: Apply chosen background color
    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, bg_color)
        background.paste(img, mask=img.split()[-1])
        processed_img = background
    else:
        processed_img = img.convert("RGB")

    print("DEBUG: Background removed ✅")

    # Step 3: FREE Local Enhancement Pipeline (Pillow only)
    print("DEBUG: Applying FREE local enhancement pipeline...")

    passport_img = processed_img.copy()

    # 3a. 2x Upscale — resolution double karo (LANCZOS = best quality)
    orig_w, orig_h = passport_img.size
    passport_img = passport_img.resize(
        (orig_w * 2, orig_h * 2), Image.LANCZOS
    )
    print(f"DEBUG: Upscaled {orig_w}x{orig_h} → {orig_w*2}x{orig_h*2}")

    # 3b. Unsharp Mask — fine details aur edges crisp karo
    passport_img = passport_img.filter(
        ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)
    )

    # 3c. Contrast boost
    passport_img = ImageEnhance.Contrast(passport_img).enhance(1.12)

    # 3d. Sharpness boost
    passport_img = ImageEnhance.Sharpness(passport_img).enhance(1.4)

    # 3e. Brightness — thoda bright karo
    passport_img = ImageEnhance.Brightness(passport_img).enhance(1.05)

    # 3f. Color saturation — skin tones natural rahe
    passport_img = ImageEnhance.Color(passport_img).enhance(1.1)

    # 3g. Second unsharp pass — final crispness
    passport_img = passport_img.filter(
        ImageFilter.UnsharpMask(radius=1, percent=80, threshold=2)
    )

    print("DEBUG: Enhancement complete ✅")
    return passport_img


@app.route("/process", methods=["POST"])
def process():
    print("==== /process endpoint hit ====")

    # Layout settings
    passport_width = int(request.form.get("width", 390))
    passport_height = int(request.form.get("height", 480))
    border = int(request.form.get("border", 2))
    spacing = int(request.form.get("spacing", 10))
    margin_x = 10
    margin_y = 10
    horizontal_gap = 10
    a4_w, a4_h = 2480, 3508

    # Background color
    bg_hex = request.form.get("bg_color", "#ffffff")
    bg_color = hex_to_rgb(bg_hex)
    print(f"DEBUG: Background color = {bg_hex} → RGB {bg_color}")

    # Collect images and their copy counts
    images_data = []

    # Multi-image mode
    i = 0
    while f"image_{i}" in request.files:
        file = request.files[f"image_{i}"]
        copies = int(request.form.get(f"copies_{i}", 6))
        images_data.append((file.read(), copies))
        i += 1

    # Fallback to single image mode
    if not images_data and "image" in request.files:
        file = request.files["image"]
        copies = int(request.form.get("copies", 6))
        images_data.append((file.read(), copies))

    if not images_data:
        return "No image uploaded", 400

    print(f"DEBUG: Processing {len(images_data)} image(s)")

    # Process all images
    passport_images = []
    for idx, (img_bytes, copies) in enumerate(images_data):
        print(f"DEBUG: Processing image {idx + 1} with {copies} copies")
        try:
            img = process_single_image(img_bytes, bg_color=bg_color)
            img = img.resize((passport_width, passport_height), Image.LANCZOS)
            img = ImageOps.expand(img, border=border, fill="black")
            passport_images.append((img, copies))
        except Exception as e:
            print(f"ERROR: {e}")
            return {"error": str(e)}, 500

    paste_w = passport_width + 2 * border
    paste_h = passport_height + 2 * border

    # Build all pages
    pages = []
    current_page = Image.new("RGB", (a4_w, a4_h), "white")
    x, y = margin_x, margin_y

    def new_page():
        nonlocal current_page, x, y
        pages.append(current_page)
        current_page = Image.new("RGB", (a4_w, a4_h), "white")
        x, y = margin_x, margin_y

    for passport_img, copies in passport_images:
        for _ in range(copies):
            if x + paste_w > a4_w - margin_x:
                x = margin_x
                y += paste_h + spacing
            if y + paste_h > a4_h - margin_y:
                new_page()
            current_page.paste(passport_img, (x, y))
            print(f"DEBUG: Placed at x={x}, y={y}")
            x += paste_w + horizontal_gap

    pages.append(current_page)
    print(f"DEBUG: Total pages = {len(pages)}")

    # Export multi-page PDF
    output = BytesIO()
    if len(pages) == 1:
        pages[0].save(output, format="PDF", dpi=(300, 300))
    else:
        pages[0].save(
            output,
            format="PDF",
            dpi=(300, 300),
            save_all=True,
            append_images=pages[1:],
        )
    output.seek(0)
    print("DEBUG: Returning PDF to client")

    return send_file(
        output,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="passport-sheet.pdf",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)