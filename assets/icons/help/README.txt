Help Overlay Icon Assets

Directory:
- assets/icons/help/
  - 76px/
  - 152px/

Filename convention:
- about.png
- contact.png
- share.png
- login.png
- logout.png
- settings.png
- account.png
- shop.png
- dropins.png

Accepted formats:
- .png (preferred)
- .webp
- .jpg
- .jpeg

Notes:
- Use square transparent images in the authored bucket size.  The repo uses
  `76px` for sub-4K windows and `152px` for 4K-or-larger windows.
- Loader matches by icon id first-found in this extension order:
  .png, .webp, .jpg, .jpeg
- Do not vertically flip or resample the icons in code; the source art is
  already oriented correctly.
- If an icon file is missing or fails to load, the UI falls back to the glyph
  placeholder automatically.
