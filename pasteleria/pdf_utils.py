"""Generador ligero de boletas en PDF con logo integrado (sin dependencias externas pesadas)."""

import os
import zlib
from django.conf import settings

try:
    from PIL import Image
except ImportError:
    Image = None


def _limpiar_texto_pdf(texto):
    """Convierte texto a WinAnsi (cp1252) y escapa caracteres especiales de PDF."""
    if texto is None:
        return ""
    s = str(texto).replace("\r", " ").replace("\n", " ")
    s_bytes = s.encode("cp1252", errors="replace")
    s_safe = s_bytes.decode("cp1252")
    return s_safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _envolver_texto(texto, max_chars=72):
    """Divide un texto largo en líneas que quepan en el ancho de la página."""
    palabras = str(texto or "").split()
    if not palabras:
        return [""]
    lineas = []
    actual = ""
    for p in palabras:
        if len(actual) + len(p) + (1 if actual else 0) <= max_chars:
            actual = f"{actual} {p}".strip()
        else:
            if actual:
                lineas.append(actual)
            actual = p[:max_chars]
    if actual:
        lineas.append(actual)
    return lineas


def _cargar_logo_pdf_rgb(bg_rgb=(252, 242, 235), size=(180, 180)):
    """Carga el logo PNG transparente y lo aplana sobre el color del banner para incrustarlo en PDF."""
    if Image is None:
        return None
    ruta_logo = os.path.join(settings.BASE_DIR, "pasteleria", "static", "pasteleria", "img", "logo.png")
    if not os.path.exists(ruta_logo):
        return None
    try:
        logo = Image.open(ruta_logo).convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        fondo = Image.new("RGBA", size, bg_rgb + (255,))
        combinado = Image.alpha_composite(fondo, logo).convert("RGB")
        raw_rgb = combinado.tobytes()
        comprimido = zlib.compress(raw_rgb)
        return size[0], size[1], comprimido
    except Exception:
        return None


def construir_pdf_boleta(
    titulo,
    subtitulo,
    datos_cliente,
    filas_detalle,
    resumen_montos,
    nota_pie="Gracias por preferir Pastelería María Bonita — Pasaje Arriba Alto.",
):
    """Construye un documento PDF 1.4 válido en bytes para descargar como boleta."""
    comandos = []

    def add_line(x1, y1, x2, y2, r=0.94, g=0.84, b=0.81, width=1):
        comandos.append(f"q {width} w {r:.2f} {g:.2f} {b:.2f} RG {x1} {y1} m {x2} {y2} l S Q")

    def add_rect(x, y, w, h, r, g, b):
        comandos.append(f"q {r:.2f} {g:.2f} {b:.2f} rg {x} {y} {w} {h} re f Q")

    def add_text(x, y, texto, size=10, bold=False, r=0.34, g=0.22, b=0.26):
        font = "F2" if bold else "F1"
        t = _limpiar_texto_pdf(texto)
        comandos.append(f"BT /{font} {size} Tf {r:.2f} {g:.2f} {b:.2f} rg {x} {y} Td ({t}) Tj ET")

    logo_data = _cargar_logo_pdf_rgb()

    # Banner superior pastel (RGB ~ 252, 242, 235)
    add_rect(40, 725, 515, 78, 0.99, 0.95, 0.92)
    add_line(40, 725, 555, 725, r=0.85, g=0.51, b=0.61, width=2)

    text_x = 55
    if logo_data:
        comandos.append("q 68 0 0 68 50 730 cm /Im1 Do Q")
        text_x = 128

    add_text(text_x, 777, "PASTELERIA MARIA BONITA", size=17, bold=True, r=0.34, g=0.22, b=0.26)
    add_text(text_x, 759, "Reposteria Artesanal — Pasaje Arriba Alto", size=10, bold=False, r=0.49, g=0.38, b=0.42)
    add_text(text_x, 738, titulo, size=11.5, bold=True, r=0.76, g=0.40, b=0.51)
    add_text(415, 738, subtitulo, size=9.5, bold=True, r=0.34, g=0.22, b=0.26)

    # Bloque de datos del cliente / pedido
    y = 695
    add_text(45, y, "DATOS DEL CLIENTE Y ENTREGA", size=10, bold=True, r=0.76, g=0.40, b=0.51)
    y -= 16
    for etiqueta, valor in datos_cliente:
        for idx, trozo in enumerate(_envolver_texto(valor, max_chars=58)):
            if idx == 0:
                add_text(45, y, f"{etiqueta}:", size=9.5, bold=True)
            add_text(165, y, trozo, size=9.5, bold=False)
            y -= 14
            if y < 120:
                break

    y -= 6
    add_line(40, y, 555, y, r=0.90, g=0.80, b=0.78, width=1)
    y -= 20

    # Encabezado de detalle
    add_rect(40, y - 5, 515, 22, 0.98, 0.91, 0.93)
    add_text(48, y + 2, "DETALLE", size=9.5, bold=True)
    add_text(335, y + 2, "CANT.", size=9.5, bold=True)
    add_text(405, y + 2, "UNITARIO", size=9.5, bold=True)
    add_text(485, y + 2, "SUBTOTAL", size=9.5, bold=True)
    y -= 24

    for descripcion, cant, unitario, subtotal in filas_detalle:
        trozos = _envolver_texto(descripcion, max_chars=46)
        for idx, trozo in enumerate(trozos):
            add_text(48, y, trozo, size=9.5, bold=False)
            if idx == 0:
                add_text(340, y, str(cant), size=9.5, bold=False)
                add_text(405, y, str(unitario), size=9.5, bold=False)
                add_text(485, y, str(subtotal), size=9.5, bold=True)
            y -= 14
            if y < 130:
                break
        y -= 4

    add_line(40, y, 555, y, r=0.90, g=0.80, b=0.78, width=1)
    y -= 22

    # Resumen de montos
    for etiqueta, valor, destacado in resumen_montos:
        size = 11.5 if destacado else 10
        color = (0.76, 0.40, 0.51) if destacado else (0.34, 0.22, 0.26)
        add_text(320, y, etiqueta, size=size, bold=True, r=color[0], g=color[1], b=color[2])
        add_text(470, y, valor, size=size, bold=True, r=color[0], g=color[1], b=color[2])
        y -= 18

    # Pie de página
    add_line(40, 68, 555, 68, r=0.90, g=0.80, b=0.78, width=0.8)
    add_text(45, 50, nota_pie, size=8.5, bold=False, r=0.49, g=0.38, b=0.42)

    stream_bytes = "\n".join(comandos).encode("cp1252", errors="replace")

    xobj_res = " /XObject << /Im1 7 0 R >>" if logo_data else ""
    objetos = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        f"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >>{xobj_res} >> /Contents 6 0 R >>\nendobj\n".encode("ascii"),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>\nendobj\n",
        f"6 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii") + stream_bytes + b"\nendstream\nendobj\n",
    ]

    if logo_data:
        lw, lh, lbytes = logo_data
        objetos.append(
            f"7 0 obj\n<< /Type /XObject /Subtype /Image /Width {lw} /Height {lh} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(lbytes)} >>\nstream\n".encode("ascii")
            + lbytes
            + b"\nendstream\nendobj\n"
        )

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objetos:
        offsets.append(len(pdf))
        pdf.extend(obj)

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objetos) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets:
        pdf.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    pdf.extend(
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)
