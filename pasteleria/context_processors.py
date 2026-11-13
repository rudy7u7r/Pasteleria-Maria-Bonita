from .models import PedidoPersonalizado, Cliente, Personal


def datos_navegacion(request):
    carrito = request.session.get('carrito', {})
    carrito_cantidad = sum(int(cant) for cant in carrito.values()) if isinstance(carrito, dict) else 0

    tortas_count = 0
    staff_rol = None
    if request.user.is_authenticated:
        if request.user.is_staff:
            if request.user.is_superuser:
                staff_rol = 'Administrador'
            else:
                pers = Personal.objects.filter(usuario=request.user).first()
                staff_rol = pers.rol if pers else 'Pastelero'
        else:
            email_usuario = (request.user.email or f"{request.user.username}@mariabonita.cl").strip().lower()
            cliente = Cliente.objects.filter(email__iexact=email_usuario).first()
            if cliente:
                tortas_count = PedidoPersonalizado.objects.filter(cliente=cliente).count()

    return {
        'carrito_cantidad': carrito_cantidad,
        'tortas_personalizadas_cantidad': tortas_count,
        'staff_rol': staff_rol,
    }
