from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "sample_source"


def make_image(path: Path, color: tuple[int, int, int], text: str, blur: bool = False) -> None:
    image = Image.new("RGB", (1200, 800), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 120, 1080, 680), outline=(255, 255, 255), width=8)
    draw.text((180, 350), text, fill=(255, 255, 255))
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(radius=8))
    image.save(path, quality=92)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    make_image(OUT / "IMG_0001_good.jpg", (80, 130, 95), "good sample")
    make_image(OUT / "IMG_0002_blurry.jpg", (80, 130, 95), "blurry sample", blur=True)
    make_image(OUT / "IMG_0003_dark.jpg", (8, 8, 12), "dark sample")
    make_image(OUT / "IMG_0004_bright.jpg", (245, 245, 245), "bright sample")
    make_image(OUT / "IMG_0005_good_duplicate.jpg", (80, 130, 95), "good sample")
    print(f"Sample images written to {OUT}")


if __name__ == "__main__":
    main()
