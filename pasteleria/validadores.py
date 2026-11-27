"""Validación y formato de datos chilenos: RUT (módulo 11) y teléfono."""
import re


def calcular_dv(cuerpo):
    """Calcula el dígito verificador para el cuerpo numérico de un RUT."""
    suma = 0
    multiplicador = 2
    for digito in reversed(str(cuerpo)):
        suma += int(digito) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        return '0'
    if resto == 10:
        return 'K'
    return str(resto)


def limpiar_rut(rut):
    """Quita puntos, guiones y espacios, y pasa la K a mayúscula."""
    return re.sub(r'[^0-9kK]', '', rut or '').upper()


def validar_rut(rut):
    """Retorna True si el RUT tiene formato válido y su dígito verificador es correcto."""
    limpio = limpiar_rut(rut)
    if len(limpio) < 8 or len(limpio) > 9:
        return False
    cuerpo, dv = limpio[:-1], limpio[-1]
    if not cuerpo.isdigit() or int(cuerpo) < 1000000:
        return False
    return calcular_dv(cuerpo) == dv


def normalizar_telefono(telefono):
    """
    Convierte un teléfono chileno al formato '+56 9 1234 5678'.
    Acepta: 912345678, 9 1234 5678, +56912345678, 56912345678, 221234567 (fijo).
    Retorna None si no es un número chileno válido de 9 dígitos.
    """
    digitos = re.sub(r'\D', '', telefono or '')
    if len(digitos) == 11 and digitos.startswith('56'):
        digitos = digitos[2:]
    if len(digitos) != 9 or digitos[0] not in '23456789':
        return None
    return f"+56 {digitos[0]} {digitos[1:5]} {digitos[5:]}"


def formatear_rut(rut):
    """Devuelve el RUT en formato 12.345.678-K (asume que ya fue validado)."""
    limpio = limpiar_rut(rut)
    cuerpo, dv = limpio[:-1], limpio[-1]
    return f"{int(cuerpo):,}".replace(',', '.') + f"-{dv}"
